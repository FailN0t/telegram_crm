"""
Bitrix24 CRM API клиент
Интеграция с Bitrix24 для работы с контактами и активностями
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode
import aiohttp

from src.config import settings
from src.logger import logger


class Bitrix24Client:
    """
    Клиент для работы с Bitrix24 REST API
    Поддерживает OAuth 2.0 и входящие webhooks
    """

    def __init__(self):
        self.domain = settings.BITRIX24_DOMAIN
        self.client_id = settings.BITRIX24_CLIENT_ID
        self.client_secret = settings.BITRIX24_CLIENT_SECRET
        self.redirect_uri = settings.BITRIX24_REDIRECT_URI
        self.webhook_url = settings.BITRIX24_WEBHOOK_URL

        self.access_token = settings.BITRIX24_ACCESS_TOKEN
        self.refresh_token = settings.BITRIX24_REFRESH_TOKEN
        self.token_expires_at = None

        if settings.BITRIX24_TOKEN_EXPIRES_AT:
            try:
                token_ts = settings.BITRIX24_TOKEN_EXPIRES_AT.replace("Z", "")
                self.token_expires_at = datetime.fromisoformat(token_ts)
            except ValueError:
                self.token_expires_at = None

        # Базовый URL зависит от режима (OAuth или Webhook)
        if self.webhook_url:
            self.base_url = self.webhook_url.rstrip("/")
            self.use_webhook = True
        else:
            self.base_url = f"https://{self.domain}/rest"
            self.use_webhook = False

        logger.info(
            f"🔗 Bitrix24 клиент инициализирован: {self.domain} "
            f"(режим: {'webhook' if self.use_webhook else 'oauth'})"
        )

    # =========================================================================
    # OAuth методы
    # =========================================================================

    async def _save_tokens(self) -> None:
        """Сохранение токенов в настройки"""
        try:
            from src.app_settings import update_settings_overrides
            values = {}
            if self.access_token:
                values["BITRIX24_ACCESS_TOKEN"] = self.access_token
            if self.refresh_token:
                values["BITRIX24_REFRESH_TOKEN"] = self.refresh_token
            if self.token_expires_at:
                values["BITRIX24_TOKEN_EXPIRES_AT"] = self.token_expires_at.isoformat()
            if values:
                _, errors = await update_settings_overrides(values)
                if errors:
                    logger.warning("⚠️ Ошибка сохранения Bitrix24 токенов: %s", errors)
        except Exception as exc:
            logger.warning("⚠️ Не удалось сохранить Bitrix24 токены: %s", exc)

    async def ensure_token_valid(self) -> bool:
        """Проверка и обновление токена если необходимо"""
        # В режиме webhook токен не нужен
        if self.use_webhook:
            return True

        if not self.access_token or not self.refresh_token:
            logger.warning("⚠️ Токены Bitrix24 не настроены!")
            return False

        # Если токен истекает в течение 5 минут - обновляем
        if self.token_expires_at and datetime.now() > (self.token_expires_at - timedelta(minutes=5)):
            logger.info("🔄 Токен истекает, обновляем...")
            return await self.refresh_access_token()

        return True

    async def refresh_access_token(self) -> bool:
        """
        Обновление access токена через refresh token

        Bitrix24 OAuth endpoint: /oauth/token/
        """
        try:
            logger.info("🔄 Обновление Bitrix24 access token...")

            async with aiohttp.ClientSession() as session:
                params = {
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                }

                async with session.get(
                    f"https://{self.domain}/oauth/token/",
                    params=params
                ) as response:
                    if response.status == 200:
                        tokens = await response.json()

                        self.access_token = tokens["access_token"]
                        self.refresh_token = tokens["refresh_token"]
                        # Bitrix24 возвращает expires_in в секундах
                        expires_in = int(tokens.get("expires_in", 3600))
                        self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)

                        logger.info("✅ Токен успешно обновлен")
                        logger.info(f"⏰ Действителен до: {self.token_expires_at}")

                        await self._save_tokens()
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка обновления токена: {error_text}")
                        return False

        except Exception as e:
            logger.error(f"❌ Исключение при обновлении токена: {e}")
            return False

    async def exchange_auth_code(self, code: str, domain: Optional[str] = None) -> Dict[str, Any]:
        """
        Обмен authorization code на access/refresh токены

        Bitrix24 OAuth flow для локальных приложений.

        Args:
            code: Authorization code от Bitrix24
            domain: Домен портала (передаётся Bitrix24 при установке)

        Returns:
            Dict с результатом: {"success": bool, "domain": str, "error": str}
        """
        target_domain = domain or self.domain

        try:
            logger.info(f"🔄 Обмен authorization code на токены Bitrix24 (domain={target_domain})...")

            async with aiohttp.ClientSession() as session:
                # Важно: используем POST с form data, включаем redirect_uri
                data = {
                    "grant_type": "authorization_code",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                }

                url = f"https://{target_domain}/oauth/token/"
                logger.info(f"🔗 OAuth URL: {url}, redirect_uri: {self.redirect_uri}")

                async with session.post(url, data=data) as response:
                    response_text = await response.text()
                    logger.info(f"📥 OAuth response status: {response.status}")

                    try:
                        tokens = json.loads(response_text)
                    except json.JSONDecodeError:
                        logger.error(f"❌ Не удалось разобрать ответ: {response_text}")
                        return {"success": False, "error": f"Invalid response: {response_text}"}

                    # Проверяем ошибки в ответе
                    if "error" in tokens:
                        error_msg = tokens.get("error_description", tokens.get("error"))
                        logger.error(f"❌ OAuth ошибка от Bitrix24: {error_msg}")
                        return {"success": False, "error": error_msg}

                    if response.status != 200:
                        logger.error(f"❌ HTTP ошибка {response.status}: {response_text}")
                        return {"success": False, "error": f"HTTP {response.status}: {response_text}"}

                    # Извлекаем актуальный домен из client_endpoint
                    client_endpoint = tokens.get("client_endpoint", f"https://{target_domain}/")
                    actual_domain = client_endpoint.replace("https://", "").replace("http://", "").split("/")[0]

                    # Обновляем домен если отличается
                    if actual_domain != self.domain:
                        logger.info(f"📝 Обновляем домен: {self.domain} → {actual_domain}")
                        self.domain = actual_domain

                    self.access_token = tokens["access_token"]
                    self.refresh_token = tokens["refresh_token"]
                    expires_in = int(tokens.get("expires_in", 3600))
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)

                    await self._save_tokens()
                    logger.info(f"✅ Bitrix24 токены успешно получены для {actual_domain}")

                    return {
                        "success": True,
                        "domain": actual_domain,
                        "expires_in": expires_in
                    }

        except Exception as e:
            logger.error(f"❌ Исключение при OAuth обмене: {e}")
            return {"success": False, "error": str(e)}

    async def save_tokens_directly(
        self,
        access_token: str,
        refresh_token: Optional[str],
        domain: str,
        expires_in: int = 3600
    ) -> Dict[str, Any]:
        """
        Сохранение токенов напрямую (без OAuth code exchange)

        Используется для ONAPPINSTALL события, когда Bitrix24 передаёт
        токены напрямую при установке локального приложения.

        Args:
            access_token: Access token от Bitrix24
            refresh_token: Refresh token (опционально)
            domain: Домен портала Bitrix24
            expires_in: Время жизни токена в секундах (по умолчанию 3600)

        Returns:
            Dict с результатом: {"success": bool, "domain": str, "error": str}
        """
        try:
            logger.info(f"💾 Сохранение Bitrix24 токенов для {domain}...")

            # Обновляем домен если отличается
            if domain != self.domain:
                logger.info(f"📝 Обновляем домен: {self.domain} → {domain}")
                self.domain = domain

            # Сохраняем токены
            self.access_token = access_token
            self.refresh_token = refresh_token
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)

            # Сохраняем в БД
            await self._save_tokens()
            logger.info(f"✅ Bitrix24 токены успешно сохранены для {domain}")

            return {
                "success": True,
                "domain": domain,
                "expires_in": expires_in
            }

        except Exception as e:
            logger.error(f"❌ Исключение при сохранении токенов: {e}")
            return {"success": False, "error": str(e)}

    def get_oauth_url(self) -> str:
        """Получить URL для OAuth авторизации"""
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
        }
        return f"https://{self.domain}/oauth/authorize/?{urlencode(params)}"

    # =========================================================================
    # API методы
    # =========================================================================

    async def _call_method(
        self,
        method: str,
        params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Универсальный вызов Bitrix24 REST API

        Args:
            method: Название метода (например, "crm.contact.get")
            params: Параметры запроса

        Returns:
            Dict с результатом или None при ошибке
        """
        if not self.use_webhook:
            if not await self.ensure_token_valid():
                return None

        try:
            if self.use_webhook:
                # Webhook URL уже содержит токен
                url = f"{self.base_url}/{method}"
            else:
                # OAuth: добавляем токен в URL
                url = f"{self.base_url}/{method}?auth={self.access_token}"

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=params or {},
                    headers={"Content-Type": "application/json"}
                ) as response:
                    data = await response.json()

                    if response.status == 200:
                        if "error" in data:
                            error = data.get("error")
                            error_desc = data.get("error_description", "")
                            logger.error(
                                f"❌ Bitrix24 API ошибка: {error} - {error_desc}"
                            )
                            return None
                        return data
                    else:
                        logger.error(
                            f"❌ Bitrix24 HTTP ошибка {response.status}: {data}"
                        )
                        return None

        except Exception as e:
            logger.error(f"❌ Исключение при вызове {method}: {e}")
            return None

    # =========================================================================
    # Контакты
    # =========================================================================

    async def find_contact_by_phone(self, phone: str) -> Optional[Dict]:
        """
        Поиск контакта по телефону

        Bitrix24 API: crm.contact.list

        Args:
            phone: Номер телефона

        Returns:
            Dict с данными контакта или None
        """
        logger.info(f"🔍 Поиск контакта в Bitrix24 по телефону: {phone}")

        result = await self._call_method("crm.contact.list", {
            "filter": {"PHONE": phone},
            "select": [
                "ID", "NAME", "LAST_NAME", "SECOND_NAME",
                "PHONE", "EMAIL",
                settings.BITRIX24_FIELD_TELEGRAM_USERNAME,
                settings.BITRIX24_FIELD_TELEGRAM_CHAT_ID,
                settings.BITRIX24_FIELD_TELEGRAM_CONSENT,
            ]
        })

        if result and result.get("result"):
            contacts = result["result"]
            if contacts:
                contact = contacts[0]
                logger.info(
                    f"✅ Найден контакт: {contact.get('NAME')} {contact.get('LAST_NAME')} "
                    f"(ID: {contact['ID']})"
                )
                return contact
            else:
                logger.warning(f"⚠️ Контакт с телефоном {phone} не найден")
                return None

        return None

    async def find_contact_by_id(self, contact_id: int) -> Optional[Dict]:
        """
        Получение контакта по ID

        Bitrix24 API: crm.contact.get

        Args:
            contact_id: ID контакта в Bitrix24

        Returns:
            Dict с данными контакта или None
        """
        logger.info(f"🔍 Получение контакта ID: {contact_id}")

        result = await self._call_method("crm.contact.get", {"id": contact_id})

        if result and result.get("result"):
            contact = result["result"]
            logger.info(
                f"✅ Контакт получен: {contact.get('NAME')} {contact.get('LAST_NAME')}"
            )
            return contact

        return None

    async def create_contact(
        self,
        first_name: str,
        last_name: Optional[str] = None,
        phone: Optional[str] = None,
        telegram_username: Optional[str] = None,
        telegram_chat_id: Optional[int] = None
    ) -> Optional[int]:
        """
        Создание нового контакта в Bitrix24

        Args:
            first_name: Имя
            last_name: Фамилия (опционально)
            phone: Телефон (опционально)
            telegram_username: Username в Telegram (опционально)
            telegram_chat_id: Chat ID в Telegram (опционально)

        Returns:
            ID созданного контакта или None
        """
        logger.info(f"➕ Создание контакта: {first_name} {last_name or ''}")

        fields = {
            "NAME": first_name
        }

        if last_name:
            fields["LAST_NAME"] = last_name

        if phone:
            fields["PHONE"] = [{"VALUE": phone, "VALUE_TYPE": "WORK"}]

        if telegram_username and settings.BITRIX24_FIELD_TELEGRAM_USERNAME:
            fields[settings.BITRIX24_FIELD_TELEGRAM_USERNAME] = telegram_username

        if telegram_chat_id and settings.BITRIX24_FIELD_TELEGRAM_CHAT_ID:
            fields[settings.BITRIX24_FIELD_TELEGRAM_CHAT_ID] = str(telegram_chat_id)

        result = await self._call_method("crm.contact.add", {"fields": fields})

        if result and result.get("result"):
            contact_id = result["result"]
            logger.info(f"✅ Контакт создан: ID {contact_id}")
            return int(contact_id)

        logger.error(f"❌ Не удалось создать контакт")
        return None

    async def get_contact_field(
        self,
        contact_id: int,
        field_name: str
    ) -> Optional[str]:
        """
        Получение значения user field контакта

        Args:
            contact_id: ID контакта
            field_name: Название UF поля (например, "UF_CRM_TELEGRAM")

        Returns:
            Значение поля или None
        """
        contact = await self.find_contact_by_id(contact_id)
        if contact:
            return contact.get(field_name)
        return None

    async def update_contact_field(
        self,
        contact_id: int,
        field_name: str,
        value: str
    ) -> bool:
        """
        Обновление user field контакта

        Bitrix24 API: crm.contact.update

        Args:
            contact_id: ID контакта
            field_name: Название UF поля
            value: Новое значение

        Returns:
            bool: Успешно ли обновлено
        """
        logger.info(
            f"📝 Обновление поля {field_name} контакта {contact_id} "
            f"на значение: {value}"
        )

        result = await self._call_method("crm.contact.update", {
            "id": contact_id,
            "fields": {field_name: value}
        })

        if result and result.get("result"):
            logger.info("✅ Поле успешно обновлено")
            return True

        return False

    async def update_contact_fields(
        self,
        contact_id: int,
        fields: Dict[str, Any]
    ) -> bool:
        """
        Обновление нескольких полей контакта

        Args:
            contact_id: ID контакта
            fields: Словарь {field_name: value}

        Returns:
            bool: Успешно ли обновлено
        """
        logger.info(f"📝 Обновление полей контакта {contact_id}: {list(fields.keys())}")

        result = await self._call_method("crm.contact.update", {
            "id": contact_id,
            "fields": fields
        })

        if result and result.get("result"):
            logger.info("✅ Поля успешно обновлены")
            return True

        return False

    # =========================================================================
    # Timeline / Примечания
    # =========================================================================

    async def add_timeline_comment(
        self,
        contact_id: int,
        text: str
    ) -> Optional[int]:
        """
        Добавление комментария в timeline контакта

        Bitrix24 API: crm.timeline.comment.add

        Args:
            contact_id: ID контакта
            text: Текст комментария

        Returns:
            ID созданного комментария или None
        """
        logger.info(f"📝 Добавление комментария в timeline контакта {contact_id}")

        result = await self._call_method("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": contact_id,
                "ENTITY_TYPE": "contact",
                "COMMENT": f"📱 Telegram (MTProto): {text}"
            }
        })

        if result and result.get("result"):
            comment_id = result["result"]
            logger.info(f"✅ Комментарий создан (ID: {comment_id})")
            return comment_id

        return None

    # Алиас для совместимости с AmoCRM интерфейсом
    async def create_note(
        self,
        contact_id: int,
        text: str,
        note_type: str = "common"
    ) -> bool:
        """
        Создание примечания к контакту (алиас для add_timeline_comment)

        Args:
            contact_id: ID контакта
            text: Текст примечания
            note_type: Тип (игнорируется в Bitrix24)

        Returns:
            bool: Успешно ли создано
        """
        comment_id = await self.add_timeline_comment(contact_id, text)
        return comment_id is not None

    # =========================================================================
    # CRM Активности
    # =========================================================================

    async def get_activity(self, activity_id: int) -> Optional[Dict]:
        """
        Получение CRM активности по ID

        Bitrix24 API: crm.activity.get

        Args:
            activity_id: ID активности

        Returns:
            Dict с данными активности или None
        """
        logger.info(f"🔍 Получение активности ID: {activity_id}")

        result = await self._call_method("crm.activity.get", {"id": activity_id})

        if result and result.get("result"):
            activity = result["result"]
            logger.info(f"✅ Активность получена: {activity.get('SUBJECT', 'N/A')}")
            return activity

        return None

    async def complete_activity(self, activity_id: int) -> bool:
        """
        Завершение CRM активности

        Bitrix24 API: crm.activity.update

        Args:
            activity_id: ID активности

        Returns:
            bool: Успешно ли завершена
        """
        logger.info(f"✅ Завершение активности ID: {activity_id}")

        result = await self._call_method("crm.activity.update", {
            "id": activity_id,
            "fields": {"COMPLETED": "Y"}
        })

        if result and result.get("result"):
            logger.info("✅ Активность завершена")
            return True

        return False

    # =========================================================================
    # Tasks (альтернатива Activities)
    # =========================================================================

    async def get_task(self, task_id: int) -> Optional[Dict]:
        """
        Получение задачи по ID (Tasks module)

        Bitrix24 API: tasks.task.get

        Args:
            task_id: ID задачи

        Returns:
            Dict с данными задачи или None
        """
        logger.info(f"🔍 Получение задачи ID: {task_id}")

        result = await self._call_method("tasks.task.get", {
            "taskId": task_id,
            "select": ["ID", "TITLE", "DESCRIPTION", "STATUS", "UF_CRM_TASK"]
        })

        if result and result.get("result"):
            task = result["result"].get("task", {})
            logger.info(f"✅ Задача получена: {task.get('title', 'N/A')}")
            return task

        return None

    async def complete_task(self, task_id: int) -> bool:
        """
        Завершение задачи

        Bitrix24 API: tasks.task.complete

        Args:
            task_id: ID задачи

        Returns:
            bool: Успешно ли завершена
        """
        logger.info(f"✅ Завершение задачи ID: {task_id}")

        result = await self._call_method("tasks.task.complete", {"taskId": task_id})

        if result is not None:
            logger.info("✅ Задача завершена")
            return True

        return False

    # =========================================================================
    # Утилиты
    # =========================================================================

    def extract_phone_from_contact(self, contact: Dict) -> Optional[str]:
        """
        Извлечение телефона из контакта Bitrix24

        В Bitrix24 PHONE - это массив объектов:
        [{"VALUE": "+7...", "VALUE_TYPE": "WORK"}, ...]
        """
        phones = contact.get("PHONE", [])
        if isinstance(phones, list) and phones:
            return phones[0].get("VALUE")
        return None

    def extract_telegram_username(self, contact: Dict) -> Optional[str]:
        """Извлечение Telegram username из UF поля"""
        return contact.get(settings.BITRIX24_FIELD_TELEGRAM_USERNAME)

    def extract_telegram_chat_id(self, contact: Dict) -> Optional[int]:
        """Извлечение Telegram chat ID из UF поля"""
        value = contact.get(settings.BITRIX24_FIELD_TELEGRAM_CHAT_ID)
        if value:
            try:
                return int(value)
            except (ValueError, TypeError):
                pass
        return None

    def has_telegram_consent(self, contact: Dict) -> bool:
        """Проверка согласия на контакт через Telegram"""
        value = contact.get(settings.BITRIX24_FIELD_TELEGRAM_CONSENT)
        if value:
            return str(value).lower() in ("1", "true", "yes", "y", "да")
        return False

    def get_contact_name(self, contact: Dict) -> str:
        """Получение полного имени контакта"""
        parts = []
        if contact.get("NAME"):
            parts.append(contact["NAME"])
        if contact.get("SECOND_NAME"):
            parts.append(contact["SECOND_NAME"])
        if contact.get("LAST_NAME"):
            parts.append(contact["LAST_NAME"])
        return " ".join(parts) if parts else f"Contact #{contact.get('ID', 'N/A')}"

    # =========================================================================
    # Поиск связанных сущностей
    # =========================================================================

    async def get_contact_id_from_activity(self, activity: Dict) -> Optional[int]:
        """
        Извлечение contact_id из активности

        В Bitrix24 активность связана через BINDINGS или OWNER_TYPE_ID
        """
        # Проверяем OWNER_TYPE_ID (1 = lead, 2 = deal, 3 = contact, 4 = company)
        owner_type = activity.get("OWNER_TYPE_ID")
        owner_id = activity.get("OWNER_ID")

        if owner_type == "3" or owner_type == 3:  # Contact
            return int(owner_id) if owner_id else None

        # Проверяем BINDINGS для связи с контактом
        bindings = activity.get("BINDINGS", [])
        for binding in bindings:
            if binding.get("OWNER_TYPE_ID") in ("3", 3):
                return int(binding.get("OWNER_ID"))

        return None

    async def get_contact_id_from_task(self, task: Dict) -> Optional[int]:
        """
        Извлечение contact_id из задачи

        В Bitrix24 задачи связаны с CRM через UF_CRM_TASK
        Формат: ["C_123", "D_456"] где C = contact, D = deal
        """
        uf_crm = task.get("ufCrmTask", []) or task.get("UF_CRM_TASK", [])

        for item in uf_crm:
            if isinstance(item, str) and item.startswith("C_"):
                try:
                    return int(item[2:])
                except ValueError:
                    pass

        return None

    # =========================================================================
    # Open Channels (Открытые линии) - Коннектор для двустороннего чата
    # =========================================================================

    async def register_connector(
        self,
        connector_id: str = "telegram_mtproto",
        name: str = "Telegram MTProto",
        icon_url: Optional[str] = None,
        placement_handler_url: Optional[str] = None
    ) -> bool:
        """
        Регистрация коннектора для Open Channels

        Bitrix24 API: imconnector.register

        Args:
            connector_id: Уникальный идентификатор коннектора
            name: Отображаемое имя коннектора
            icon_url: URL иконки коннектора (опционально)

        Returns:
            bool: Успешно ли зарегистрирован
        """
        logger.info(f"📝 Регистрация коннектора Open Channels: {connector_id}")

        # Telegram logo SVG в base64 (если иконка не указана)
        default_icon = (
            "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDgiIGhlaWdodD0iNDgiIHZpZXdCb3g9IjAgMCA0OCA0OCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPGNpcmNsZSBjeD0iMjQiIGN5PSIyNCIgcj0iMjQiIGZpbGw9IiMwMDg4Y2MiLz4KPHBhdGggZD0iTTEwLjUgMjMuNUwyMC41IDE5LjVMMzIuNSAxNS41TDM4LjUgMTMuNUMzOS41IDEzLjUgNDAuNSAxNC41IDQwLjUgMTUuNUw0MC41IDE3LjVMMzguNSAyOC41TDM2LjUgMzQuNUMzNi41IDM1LjUgMzUuNSAzNi41IDM0LjUgMzYuNUMzMy41IDM2LjUgMzMgMzYgMzIuNSAzNS41TDI1LjUgMzAuNUwyMi41IDI4LjVMMTcuNSAzMy41QzE2LjUgMzQuNSAxNS41IDM0LjUgMTQuNSAzMy41QzEzLjUgMzIuNSAxMy41IDMxLjUgMTMuNSAzMC41TDEzLjUgMjQuNUwxMC41IDIzLjVaIiBmaWxsPSJ3aGl0ZSIvPgo8L3N2Zz4K"
        )

        params = {
            "ID": connector_id,
            "NAME": name,
            "ICON": {
                "DATA_IMAGE": icon_url or default_icon
            }
        }

        # Добавляем PLACEMENT_HANDLER если указан
        if placement_handler_url:
            params["PLACEMENT_HANDLER"] = placement_handler_url

        result = await self._call_method("imconnector.register", params)

        if result and result.get("result"):
            logger.info(f"✅ Коннектор {connector_id} зарегистрирован")
            return True

        # Коннектор может быть уже зарегистрирован
        if result and "error" in result:
            error = result.get("error", "")
            if "CONNECTOR_ALREADY_EXISTS" in str(error):
                logger.info(f"ℹ️ Коннектор {connector_id} уже зарегистрирован")
                return True

        return False

    async def unregister_connector(self, connector_id: str = "telegram_mtproto") -> bool:
        """
        Удаление регистрации коннектора

        Bitrix24 API: imconnector.unregister

        Args:
            connector_id: Идентификатор коннектора

        Returns:
            bool: Успешно ли удален
        """
        logger.info(f"🗑️ Удаление коннектора: {connector_id}")

        result = await self._call_method("imconnector.unregister", {
            "ID": connector_id
        })

        if result and result.get("result"):
            logger.info(f"✅ Коннектор {connector_id} удален")
            return True

        return False

    async def activate_connector(
        self,
        connector_id: str = "telegram_mtproto",
        line_id: int = 0
    ) -> bool:
        """
        Активация коннектора на линии Open Channels

        Bitrix24 API: imconnector.activate

        Args:
            connector_id: Идентификатор коннектора
            line_id: ID линии (0 = основная линия)

        Returns:
            bool: Успешно ли активирован
        """
        logger.info(f"🔌 Активация коннектора {connector_id} на линии {line_id}")

        result = await self._call_method("imconnector.activate", {
            "CONNECTOR": connector_id,
            "LINE": line_id,
            "ACTIVE": 1
        })

        if result and result.get("result"):
            logger.info(f"✅ Коннектор активирован на линии {line_id}")
            return True

        return False

    async def deactivate_connector(
        self,
        connector_id: str = "telegram_mtproto",
        line_id: int = 0
    ) -> bool:
        """
        Деактивация коннектора на линии

        Args:
            connector_id: Идентификатор коннектора
            line_id: ID линии

        Returns:
            bool: Успешно ли деактивирован
        """
        logger.info(f"🔌 Деактивация коннектора {connector_id} на линии {line_id}")

        result = await self._call_method("imconnector.activate", {
            "CONNECTOR": connector_id,
            "LINE": line_id,
            "ACTIVE": 0
        })

        if result and result.get("result"):
            logger.info(f"✅ Коннектор деактивирован")
            return True

        return False

    async def get_connector_status(
        self,
        connector_id: str = "telegram_mtproto",
        line_id: int = 0
    ) -> Optional[Dict]:
        """
        Получение статуса коннектора

        Bitrix24 API: imconnector.status

        Args:
            connector_id: Идентификатор коннектора
            line_id: ID линии

        Returns:
            Dict со статусом или None
        """
        result = await self._call_method("imconnector.status", {
            "CONNECTOR": connector_id,
            "LINE": line_id
        })

        if result and result.get("result"):
            return result["result"]

        return None

    async def get_open_lines(self) -> List[Dict]:
        """
        Получение списка открытых линий

        Bitrix24 API: imopenlines.config.list.get

        Returns:
            Список линий
        """
        logger.info("📋 Получение списка открытых линий")

        result = await self._call_method("imopenlines.config.list.get", {})

        if result and result.get("result"):
            lines = result["result"]
            logger.info(f"✅ Найдено {len(lines)} линий")
            return lines

        return []

    async def send_message_to_open_line(
        self,
        connector_id: str,
        line_id: int,
        chat_id: str,
        user_id: str,
        user_name: str,
        message_text: str,
        message_id: Optional[str] = None,
        files: Optional[List[Dict]] = None
    ) -> Optional[Dict]:
        """
        Отправка сообщения в Open Line (от внешнего пользователя в Bitrix24)

        Используется для пересылки сообщений из Telegram в Bitrix24

        Bitrix24 API: imconnector.send.messages

        Args:
            connector_id: ID коннектора
            line_id: ID линии
            chat_id: ID чата (внешний, например telegram_chat_id)
            user_id: ID пользователя (внешний, например telegram_user_id)
            user_name: Имя пользователя для отображения
            message_text: Текст сообщения
            message_id: Внешний ID сообщения (опционально)
            files: Список файлов (опционально)

        Returns:
            Dict с результатом или None
        """
        logger.info(
            f"📤 Отправка сообщения в Open Line: line={line_id}, "
            f"user={user_name}, text={message_text[:50]}..."
        )

        message = {
            "user": {
                "id": str(user_id),
                "name": user_name,
                # Дополнительные поля
                # "avatar": "URL аватара",
                # "url": "URL профиля"
            },
            "message": {
                "text": message_text
            },
            "chat": {
                "id": str(chat_id)
            }
        }

        if message_id:
            message["message"]["id"] = str(message_id)

        # Добавление файлов
        if files:
            message["message"]["files"] = files

        params = {
            "CONNECTOR": connector_id,
            "LINE": line_id,
            "MESSAGES": [message]
        }

        result = await self._call_method("imconnector.send.messages", params)

        if result and result.get("result"):
            logger.info("✅ Сообщение отправлено в Open Line")
            return result["result"]

        return None

    async def send_status_delivery(
        self,
        connector_id: str,
        line_id: int,
        message_ids: List[str]
    ) -> bool:
        """
        Отправка статуса доставки сообщений

        Bitrix24 API: imconnector.send.status.delivery

        Args:
            connector_id: ID коннектора
            line_id: ID линии
            message_ids: Список ID сообщений

        Returns:
            bool: Успешно ли отправлен статус
        """
        result = await self._call_method("imconnector.send.status.delivery", {
            "CONNECTOR": connector_id,
            "LINE": line_id,
            "MESSAGES": [{"id": mid} for mid in message_ids]
        })

        return result is not None and result.get("result")

    async def send_status_reading(
        self,
        connector_id: str,
        line_id: int,
        chat_id: str,
        message_ids: List[str]
    ) -> bool:
        """
        Отправка статуса прочтения сообщений

        Bitrix24 API: imconnector.send.status.reading

        Args:
            connector_id: ID коннектора
            line_id: ID линии
            chat_id: ID чата
            message_ids: Список ID сообщений

        Returns:
            bool: Успешно ли отправлен статус
        """
        result = await self._call_method("imconnector.send.status.reading", {
            "CONNECTOR": connector_id,
            "LINE": line_id,
            "CHAT": {"id": str(chat_id)},
            "MESSAGES": [{"id": mid} for mid in message_ids]
        })

        return result is not None and result.get("result")

    async def update_user_in_chat(
        self,
        connector_id: str,
        line_id: int,
        chat_id: str,
        user_id: str,
        user_name: str,
        avatar_url: Optional[str] = None
    ) -> bool:
        """
        Обновление информации о пользователе в чате

        Bitrix24 API: imconnector.chat.user.update

        Args:
            connector_id: ID коннектора
            line_id: ID линии
            chat_id: ID чата
            user_id: ID пользователя
            user_name: Имя пользователя
            avatar_url: URL аватара

        Returns:
            bool: Успешно ли обновлено
        """
        params = {
            "CONNECTOR": connector_id,
            "LINE": line_id,
            "CHAT_ID": str(chat_id),
            "USER": {
                "id": str(user_id),
                "name": user_name
            }
        }

        if avatar_url:
            params["USER"]["avatar"] = avatar_url

        result = await self._call_method("imconnector.chat.user.update", params)

        return result is not None and result.get("result")

    async def delete_chat(
        self,
        connector_id: str,
        line_id: int,
        chat_id: str
    ) -> bool:
        """
        Удаление/закрытие чата в Open Line

        Bitrix24 API: imconnector.chat.delete

        Args:
            connector_id: ID коннектора
            line_id: ID линии
            chat_id: ID чата

        Returns:
            bool: Успешно ли удален
        """
        result = await self._call_method("imconnector.delete.chat", {
            "CONNECTOR": connector_id,
            "LINE": line_id,
            "CHAT": {"id": str(chat_id)}
        })

        return result is not None and result.get("result")

    # =========================================================================
    # CRM + Open Channels: связь контакта с чатом
    # =========================================================================

    async def link_chat_to_contact(
        self,
        chat_id: int,
        contact_id: int
    ) -> bool:
        """
        Привязка чата Open Line к контакту CRM

        Bitrix24 API: imopenlines.crm.chat.user.add

        Args:
            chat_id: ID чата в Open Lines
            contact_id: ID контакта CRM

        Returns:
            bool: Успешно ли привязано
        """
        logger.info(f"🔗 Привязка чата {chat_id} к контакту {contact_id}")

        result = await self._call_method("imopenlines.crm.chat.user.add", {
            "CHAT_ID": chat_id,
            "CRM_ENTITY_TYPE": "CONTACT",
            "CRM_ENTITY": contact_id
        })

        if result and result.get("result"):
            logger.info("✅ Чат привязан к контакту")
            return True

        return False

    async def get_chat_crm_info(self, chat_id: int) -> Optional[Dict]:
        """
        Получение CRM информации о чате

        Bitrix24 API: imopenlines.crm.chat.get

        Args:
            chat_id: ID чата

        Returns:
            Dict с CRM информацией или None
        """
        result = await self._call_method("imopenlines.crm.chat.get", {
            "CHAT_ID": chat_id
        })

        if result and result.get("result"):
            return result["result"]

        return None

    # =========================================================================
    # Регистрация webhooks для Open Channels событий
    # =========================================================================

    async def register_open_line_events(self, handler_url: str) -> Dict[str, bool]:
        """
        Регистрация обработчиков событий Open Channels

        Events:
        - ONIMCONNECTORMESSAGEADD: сообщение от оператора → внешнему пользователю
        - ONIMCONNECTORLINEJOIN: коннектор подключен к линии
        - ONIMCONNECTORLINEDELETE: коннектор отключен от линии
        - ONIMCONNECTORMESSAGEUPDATE: сообщение обновлено
        - ONIMCONNECTORMESSAGEDELETE: сообщение удалено

        Args:
            handler_url: URL обработчика событий

        Returns:
            Dict с результатами регистрации для каждого события
        """
        logger.info(f"📝 Регистрация Open Line событий на {handler_url}")

        events = [
            "ONIMCONNECTORMESSAGEADD",
            "ONIMCONNECTORLINEJOIN",
            "ONIMCONNECTORLINEDELETE",
            "ONIMCONNECTORMESSAGEUPDATE",
            "ONIMCONNECTORMESSAGEDELETE"
        ]

        results = {}
        for event in events:
            result = await self._call_method("event.bind", {
                "event": event,
                "handler": handler_url,
                "auth_type": 0  # Использовать текущую авторизацию
            })
            success = result is not None and result.get("result")
            results[event] = success
            if success:
                logger.info(f"✅ Событие {event} зарегистрировано")
            else:
                logger.warning(f"⚠️ Не удалось зарегистрировать {event}")

        return results

    async def unregister_open_line_events(self, handler_url: str) -> Dict[str, bool]:
        """
        Удаление обработчиков событий Open Channels

        Args:
            handler_url: URL обработчика событий

        Returns:
            Dict с результатами удаления
        """
        logger.info(f"🗑️ Удаление Open Line событий для {handler_url}")

        events = [
            "ONIMCONNECTORMESSAGEADD",
            "ONIMCONNECTORLINEJOIN",
            "ONIMCONNECTORLINEDELETE",
            "ONIMCONNECTORMESSAGEUPDATE",
            "ONIMCONNECTORMESSAGEDELETE"
        ]

        results = {}
        for event in events:
            result = await self._call_method("event.unbind", {
                "event": event,
                "handler": handler_url
            })
            results[event] = result is not None
            if result:
                logger.info(f"✅ Событие {event} удалено")

        return results

    async def get_registered_events(self) -> List[Dict]:
        """
        Получение списка зарегистрированных событий

        Bitrix24 API: event.get

        Returns:
            Список зарегистрированных событий
        """
        result = await self._call_method("event.get", {})

        if result and result.get("result"):
            return result["result"]

        return []

    # =========================================================================
    # Инициализация Open Channels интеграции
    # =========================================================================

    async def setup_open_channels(
        self,
        connector_id: str = "telegram_mtproto",
        connector_name: str = "Telegram MTProto",
        webhook_url: Optional[str] = None,
        line_id: int = 0,
        placement_handler_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Полная настройка Open Channels интеграции

        1. Регистрация коннектора
        2. Активация на линии
        3. Регистрация событий

        Args:
            connector_id: ID коннектора
            connector_name: Имя коннектора
            webhook_url: URL для событий (если не указан - не регистрируем)
            line_id: ID линии (0 = основная)

        Returns:
            Dict с результатами настройки
        """
        logger.info("🚀 Настройка Open Channels интеграции...")

        results = {
            "connector_registered": False,
            "connector_activated": False,
            "events_registered": {},
            "status": None,
            "error": None
        }

        try:
            # 1. Регистрация коннектора
            results["connector_registered"] = await self.register_connector(
                connector_id=connector_id,
                name=connector_name,
                placement_handler_url=placement_handler_url
            )

            if not results["connector_registered"]:
                results["error"] = "Failed to register connector"
                return results

            # 2. Активация коннектора
            results["connector_activated"] = await self.activate_connector(
                connector_id=connector_id,
                line_id=line_id
            )

            # 3. Регистрация событий (если указан webhook)
            if webhook_url:
                results["events_registered"] = await self.register_open_line_events(
                    handler_url=webhook_url
                )

            # 4. Получение статуса
            results["status"] = await self.get_connector_status(
                connector_id=connector_id,
                line_id=line_id
            )

            logger.info("✅ Open Channels интеграция настроена")

        except Exception as e:
            logger.error(f"❌ Ошибка настройки Open Channels: {e}")
            results["error"] = str(e)

        return results
