"""
Bridge между CRM (AmoCRM/Bitrix24) и Telegram
Основная бизнес-логика интеграции
"""

from typing import Tuple, Optional, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.telegram_manager import TelegramClientManager
from src.amocrm_client import AmoCRMClient
from src.bitrix24_client import Bitrix24Client
from src.database import ChatMapping, MessageHistory
from src.config import settings
from src.logger import logger


# Тип CRM клиента
CRMClient = Union[AmoCRMClient, Bitrix24Client, None]


class CRMTelegramBridge:
    """
    Мост между CRM (AmoCRM или Bitrix24) и Telegram
    Координирует работу обоих клиентов
    """

    def __init__(
        self,
        telegram: TelegramClientManager,
        crm_client: CRMClient
    ):
        self.telegram = telegram
        self.crm = crm_client
        self.crm_provider = settings.CRM_PROVIDER.lower()

        if self.crm_provider == "bitrix24":
            logger.info("🌉 Bridge инициализирован (CRM: Bitrix24)")
        else:
            logger.info("🌉 Bridge инициализирован (CRM: AmoCRM)")

    # =========================================================================
    # Универсальные методы для работы с CRM
    # =========================================================================

    def _is_bitrix24(self) -> bool:
        """Проверка, используется ли Bitrix24"""
        return self.crm_provider == "bitrix24"

    async def _get_contact_consent(self, contact_id: int) -> bool:
        """Проверка согласия контакта на связь через Telegram"""
        if not self.crm:
            return True  # Если CRM нет, пропускаем проверку

        if self._is_bitrix24():
            contact = await self.crm.find_contact_by_id(contact_id)
            if contact:
                return self.crm.has_telegram_consent(contact)
            return False
        else:
            # AmoCRM
            if settings.AMOCRM_FIELD_TELEGRAM_CONSENT:
                has_consent = await self.crm.get_contact_field(
                    contact_id,
                    settings.AMOCRM_FIELD_TELEGRAM_CONSENT
                )
                return has_consent and has_consent.lower() == 'true'
            return True

    async def _create_crm_note(self, contact_id: int, text: str) -> bool:
        """Создание примечания/комментария в CRM"""
        if not self.crm:
            return False

        if self._is_bitrix24():
            return await self.crm.create_note(contact_id, text)
        else:
            return await self.crm.create_note(contact_id, text)

    async def _update_telegram_chat_id(self, contact_id: int, chat_id: int) -> bool:
        """Обновление Telegram chat_id в CRM"""
        if not self.crm:
            return False

        if self._is_bitrix24():
            return await self.crm.update_contact_field(
                contact_id,
                settings.BITRIX24_FIELD_TELEGRAM_CHAT_ID,
                str(chat_id)
            )
        else:
            if settings.AMOCRM_FIELD_TELEGRAM_CHAT_ID:
                return await self.crm.update_contact_field(
                    contact_id,
                    settings.AMOCRM_FIELD_TELEGRAM_CHAT_ID,
                    str(chat_id)
                )
            return True

    async def _get_contact(self, contact_id: int) -> Optional[dict]:
        """Получение контакта из CRM"""
        if not self.crm:
            return None
        return await self.crm.find_contact_by_id(contact_id)

    def _extract_phone_from_contact(self, contact: dict) -> Optional[str]:
        """Извлечение телефона из контакта"""
        if self._is_bitrix24():
            return self.crm.extract_phone_from_contact(contact)
        else:
            # AmoCRM
            custom_fields = contact.get('custom_fields_values', [])
            for field in custom_fields:
                if field.get('field_code') == 'PHONE':
                    values = field.get('values', [])
                    if values:
                        return values[0].get('value')
            return None

    def _extract_username_from_contact(self, contact: dict) -> Optional[str]:
        """Извлечение Telegram username из контакта"""
        if self._is_bitrix24():
            return self.crm.extract_telegram_username(contact)
        else:
            # AmoCRM
            custom_fields = contact.get('custom_fields_values', [])
            for field in custom_fields:
                if field.get('field_id') == settings.AMOCRM_FIELD_TELEGRAM_USERNAME:
                    values = field.get('values', [])
                    if values:
                        return values[0].get('value')
            return None

    # =========================================================================
    # Основные методы Bridge
    # =========================================================================

    async def send_message_from_crm(
        self,
        db: AsyncSession,
        contact_id: int,
        phone: Optional[str],
        username: Optional[str],
        message: str,
        account_id: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Отправка сообщения клиенту из CRM

        Args:
            db: Сессия БД
            contact_id: ID контакта в CRM
            phone: Номер телефона (опционально)
            username: Username в Telegram (опционально)
            message: Текст сообщения

        Returns:
            (success, message): Результат отправки
        """
        crm_name = "Bitrix24" if self._is_bitrix24() else "AmoCRM"

        if not self.crm:
            return False, f"{crm_name} is not configured"

        logger.info(
            f"📤 Запрос на отправку сообщения ({crm_name}): "
            f"contact_id={contact_id}, phone={phone}, username={username}"
        )

        # Проверяем согласие клиента
        has_consent = await self._get_contact_consent(contact_id)
        if not has_consent:
            error_msg = "Клиент не дал согласия на контакт через Telegram"
            logger.error(f"❌ {error_msg}")
            await self._create_crm_note(contact_id, f"❌ {error_msg}")
            return False, error_msg

        # Проверяем, есть ли уже связь в БД
        # Используем общее поле для обеих CRM (crm_contact_id)
        # TODO: После миграции БД использовать crm_contact_id
        mapping_query = {"amocrm_contact_id": contact_id}
        if account_id:
            mapping_query["account_id"] = account_id
        result = await db.execute(
            select(ChatMapping).filter_by(**mapping_query)
        )
        mapping = result.scalars().first()

        if not account_id and mapping:
            account_id = mapping.account_id

        if not account_id:
            account_id = await self.telegram.select_account_id()

        if not account_id:
            return False, "no_active_accounts"

        client = await self.telegram.get_client(account_id)

        user = None

        if mapping and mapping.telegram_chat_id:
            # Есть связь - получаем пользователя по chat_id
            try:
                user = await client.client.get_entity(mapping.telegram_chat_id)
                logger.info(f"✅ Найден по сохраненному chat_id: {mapping.telegram_chat_id}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось получить по chat_id: {e}")
                user = None

        # Если нет в БД или не удалось получить - ищем
        if not user:
            # Сначала пробуем по username (быстрее и надежнее)
            if username:
                user = await client.find_user_by_username(username)

            # Если не нашли, пробуем по телефону
            if not user and phone:
                user = await client.find_user_by_phone(phone)

        if not user:
            error_msg = "Пользователь не найден в Telegram"
            logger.error(f"❌ {error_msg}")
            await self._create_crm_note(contact_id, f"❌ {error_msg}")
            return False, error_msg

        # Определяем, первое ли это сообщение
        is_new_chat = not mapping or not mapping.telegram_chat_id

        # Отправляем сообщение
        success, result = await client.send_message_to_user(
            user,
            message,
            is_new_chat
        )

        if success:
            # Сохраняем/обновляем связь в БД
            if not mapping:
                mapping = ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=user.id,
                    telegram_username=user.username,
                    telegram_first_name=user.first_name,
                    telegram_last_name=user.last_name,
                    phone_number=phone,
                    amocrm_contact_id=contact_id,  # TODO: переименовать в crm_contact_id
                    is_active=True,
                    has_consent=True
                )
                db.add(mapping)
            else:
                mapping.telegram_chat_id = user.id
                mapping.telegram_username = user.username
                mapping.is_active = True
            await db.commit()

            # Сохраняем сообщение в историю
            history = MessageHistory(
                account_id=account_id,
                chat_mapping_id=mapping.id,
                amocrm_contact_id=contact_id,  # TODO: переименовать в crm_contact_id
                direction='outbound',
                message_text=message,
                message_type='text',
                telegram_chat_id=user.id,
                status='sent'
            )
            db.add(history)
            await db.commit()

            # Обновляем поле chat_id в CRM
            await self._update_telegram_chat_id(contact_id, user.id)

            # Создаем примечание в CRM
            await self._create_crm_note(
                contact_id,
                f"✅ Отправлено: {message[:100]}{'...' if len(message) > 100 else ''}"
            )

            logger.info(f"✅ Сообщение успешно отправлено и сохранено")

        else:
            # Создаем примечание об ошибке
            await self._create_crm_note(
                contact_id,
                f"❌ Ошибка отправки: {result}"
            )

            # Если FloodWait - сохраняем в БД для повторной отправки
            if "FloodWait" in result:
                history = MessageHistory(
                    account_id=account_id,
                    chat_mapping_id=mapping.id if mapping else 0,
                    amocrm_contact_id=contact_id,
                    direction='outbound',
                    message_text=message,
                    message_type='text',
                    telegram_chat_id=user.id if user else 0,
                    status='failed',
                    error_message=result
                )
                db.add(history)
                await db.commit()

        return success, result

    # Алиас для обратной совместимости
    async def send_message_from_amocrm(
        self,
        db: AsyncSession,
        contact_id: int,
        phone: Optional[str],
        username: Optional[str],
        message: str,
        account_id: Optional[int] = None
    ) -> Tuple[bool, str]:
        """Алиас для send_message_from_crm (обратная совместимость)"""
        return await self.send_message_from_crm(
            db, contact_id, phone, username, message, account_id
        )

    async def handle_crm_task(
        self,
        db: AsyncSession,
        task_id: Optional[int] = None,
        activity_id: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Обработка задачи/активности из CRM

        Args:
            db: Сессия БД
            task_id: ID задачи (AmoCRM или Bitrix24 Tasks)
            activity_id: ID активности (Bitrix24 Activities)

        Returns:
            (success, message): Результат обработки
        """
        crm_name = "Bitrix24" if self._is_bitrix24() else "AmoCRM"

        if not self.crm:
            return False, f"{crm_name} is not configured"

        if self._is_bitrix24():
            # Bitrix24: приоритет activity_id, затем task_id
            if activity_id:
                logger.info(f"📋 Обработка activity Bitrix24: {activity_id}")
                return await self._handle_bitrix24_activity(db, activity_id)
            elif task_id:
                logger.info(f"📋 Обработка task Bitrix24: {task_id}")
                return await self._handle_bitrix24_task(db, task_id)
            else:
                return False, "activity_id or task_id is required"
        else:
            # AmoCRM: только task_id
            if not task_id:
                return False, "task_id is required"
            logger.info(f"📋 Обработка задачи AmoCRM: {task_id}")
            return await self._handle_amocrm_task(db, task_id)

    # Алиас для обратной совместимости
    async def handle_amocrm_task(
        self,
        db: AsyncSession,
        task_id: int
    ) -> Tuple[bool, str]:
        """Алиас для handle_crm_task (обратная совместимость)"""
        return await self.handle_crm_task(db, task_id)

    async def _handle_amocrm_task(
        self,
        db: AsyncSession,
        task_id: int
    ) -> Tuple[bool, str]:
        """Обработка задачи из AmoCRM"""
        # Получаем задачу
        task = await self.crm.get_task(task_id)
        if not task:
            return False, "Задача не найдена"

        # Извлекаем данные
        contact_id = task.get('entity_id')
        task_text = task.get('text', '')

        if not contact_id:
            return False, "У задачи нет связанного контакта"

        if not task_text:
            return False, "Задача не содержит текста"

        # Получаем контакт
        contact = await self.crm.find_contact_by_id(contact_id)
        if not contact:
            return False, "Контакт не найден"

        # Извлекаем телефон и username
        phone = self._extract_phone_from_contact(contact)
        username = self._extract_username_from_contact(contact)

        # Отправляем сообщение
        success, result = await self.send_message_from_crm(
            db,
            contact_id,
            phone,
            username,
            task_text
        )

        # Если успешно - завершаем задачу
        if success:
            await self.crm.complete_task(task_id)
            logger.info(f"✅ Задача {task_id} завершена")

        return success, result

    async def _handle_bitrix24_activity(
        self,
        db: AsyncSession,
        activity_id: int
    ) -> Tuple[bool, str]:
        """Обработка активности (CRM Activity) из Bitrix24"""
        # Получаем активность
        activity = await self.crm.get_activity(activity_id)
        if not activity:
            return False, "Активность не найдена"

        # Извлекаем contact_id
        contact_id = await self.crm.get_contact_id_from_activity(activity)
        if not contact_id:
            return False, "У активности нет связанного контакта"

        # Текст из DESCRIPTION или SUBJECT
        activity_text = activity.get('DESCRIPTION') or activity.get('SUBJECT', '')
        if not activity_text:
            return False, "Активность не содержит текста"

        # Получаем контакт
        contact = await self.crm.find_contact_by_id(contact_id)
        if not contact:
            return False, "Контакт не найден"

        # Извлекаем телефон и username
        phone = self._extract_phone_from_contact(contact)
        username = self._extract_username_from_contact(contact)

        # Отправляем сообщение
        success, result = await self.send_message_from_crm(
            db,
            contact_id,
            phone,
            username,
            activity_text
        )

        # Если успешно - завершаем активность
        if success:
            await self.crm.complete_activity(activity_id)
            logger.info(f"✅ Активность {activity_id} завершена")

        return success, result

    async def _handle_bitrix24_task(
        self,
        db: AsyncSession,
        task_id: int
    ) -> Tuple[bool, str]:
        """Обработка задачи (Tasks) из Bitrix24"""
        # Получаем задачу
        task = await self.crm.get_task(task_id)
        if not task:
            return False, "Задача не найдена"

        # Извлекаем contact_id из UF_CRM_TASK (формат: C_123)
        uf_crm = task.get('ufCrmTask') or task.get('UF_CRM_TASK') or []
        contact_id = None
        for crm_link in uf_crm:
            if isinstance(crm_link, str) and crm_link.startswith('C_'):
                contact_id = int(crm_link[2:])
                break

        if not contact_id:
            return False, "У задачи нет связанного контакта"

        # Текст из DESCRIPTION или TITLE
        task_text = task.get('description') or task.get('DESCRIPTION') or ''
        if not task_text:
            task_text = task.get('title') or task.get('TITLE') or ''
        if not task_text:
            return False, "Задача не содержит текста"

        # Получаем контакт
        contact = await self.crm.find_contact_by_id(contact_id)
        if not contact:
            return False, "Контакт не найден"

        # Извлекаем телефон и username
        phone = self._extract_phone_from_contact(contact)
        username = self._extract_username_from_contact(contact)

        # Отправляем сообщение
        success, result = await self.send_message_from_crm(
            db,
            contact_id,
            phone,
            username,
            task_text
        )

        # Если успешно - завершаем задачу
        if success:
            await self.crm.complete_task(task_id)
            logger.info(f"✅ Задача {task_id} завершена")

        return success, result

    async def get_stats(self, db: AsyncSession) -> dict:
        """Получить общую статистику"""
        total_mappings = await db.scalar(
            select(func.count()).select_from(ChatMapping)
        )
        active_mappings = await db.scalar(
            select(func.count()).select_from(ChatMapping).filter_by(is_active=True)
        )
        total_messages = await db.scalar(
            select(func.count()).select_from(MessageHistory)
        )

        telegram_status = await self.telegram.get_status()

        return {
            "crm_provider": self.crm_provider,
            "telegram": {
                "accounts": telegram_status,
                "active_accounts": len([a for a in telegram_status if a.get("is_active")]),
            },
            "mappings": {
                "total": total_mappings,
                "active": active_mappings,
            },
            "messages": {
                "total": total_messages,
            }
        }

    # =========================================================================
    # Bitrix24 Open Channels - двусторонний чат
    # =========================================================================

    async def forward_to_open_line(
        self,
        db: AsyncSession,
        telegram_chat_id: int,
        telegram_user_id: int,
        user_name: str,
        message_text: str,
        message_id: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Пересылка сообщения из Telegram в Bitrix24 Open Line

        Используется для отправки входящих сообщений от клиента в чат Bitrix24

        Args:
            db: Сессия БД
            telegram_chat_id: ID чата Telegram (используется как внешний chat_id)
            telegram_user_id: ID пользователя Telegram (используется как внешний user_id)
            user_name: Имя пользователя для отображения в Bitrix24
            message_text: Текст сообщения
            message_id: ID сообщения в Telegram (опционально)

        Returns:
            (success, message): Результат отправки
        """
        if not self._is_bitrix24():
            return False, "Open Channels available only for Bitrix24"

        if not self.crm:
            return False, "Bitrix24 client not configured"

        if not settings.BITRIX24_OPEN_CHANNELS_ENABLED:
            return False, "Open Channels disabled"

        logger.info(
            f"📤 Пересылка сообщения в Open Line: "
            f"chat_id={telegram_chat_id}, user={user_name}"
        )

        try:
            result = await self.crm.send_message_to_open_line(
                connector_id=settings.BITRIX24_CONNECTOR_ID,
                line_id=settings.BITRIX24_LINE_ID,
                chat_id=str(telegram_chat_id),
                user_id=str(telegram_user_id),
                user_name=user_name,
                message_text=message_text,
                message_id=str(message_id) if message_id else None
            )

            if result:
                logger.info(f"✅ Сообщение переслано в Open Line")

                # Пытаемся привязать чат к контакту CRM (если есть связь)
                mapping_result = await db.execute(
                    select(ChatMapping).filter_by(telegram_chat_id=telegram_chat_id)
                )
                mapping = mapping_result.scalars().first()

                if mapping and mapping.amocrm_contact_id:
                    # Получаем ID чата из результата (если есть)
                    bitrix_chat_id = result.get("CHAT_ID") or result.get("chat_id")
                    if bitrix_chat_id:
                        try:
                            await self.crm.link_chat_to_contact(
                                chat_id=int(bitrix_chat_id),
                                contact_id=mapping.amocrm_contact_id
                            )
                        except Exception as e:
                            logger.warning(f"⚠️ Не удалось привязать чат к контакту: {e}")

                return True, "Message forwarded to Open Line"

            return False, "Failed to send message to Open Line"

        except Exception as e:
            logger.error(f"❌ Ошибка пересылки в Open Line: {e}")
            return False, str(e)

    async def handle_incoming_message(
        self,
        db: AsyncSession,
        telegram_chat_id: int,
        telegram_user_id: int,
        user_first_name: str,
        user_last_name: Optional[str],
        username: Optional[str],
        message_text: str,
        message_id: int
    ) -> Tuple[bool, str]:
        """
        Обработка входящего сообщения из Telegram

        Если включены Open Channels - пересылает в Bitrix24
        Также создает примечание в CRM (если есть связь с контактом)

        Args:
            db: Сессия БД
            telegram_chat_id: ID чата Telegram
            telegram_user_id: ID пользователя
            user_first_name: Имя пользователя
            user_last_name: Фамилия пользователя
            username: Username в Telegram
            message_text: Текст сообщения
            message_id: ID сообщения

        Returns:
            (success, message): Результат обработки
        """
        # Формируем отображаемое имя
        user_name = user_first_name
        if user_last_name:
            user_name = f"{user_first_name} {user_last_name}"
        if username:
            user_name = f"{user_name} (@{username})"

        # Если Bitrix24 с Open Channels - пересылаем в Open Line
        if (
            self._is_bitrix24()
            and settings.BITRIX24_OPEN_CHANNELS_ENABLED
            and self.crm
        ):
            return await self.forward_to_open_line(
                db,
                telegram_chat_id,
                telegram_user_id,
                user_name,
                message_text,
                message_id
            )

        # Для AmoCRM или без Open Channels - только примечание в CRM
        mapping_result = await db.execute(
            select(ChatMapping).filter_by(telegram_chat_id=telegram_chat_id)
        )
        mapping = mapping_result.scalars().first()

        if mapping and mapping.amocrm_contact_id and self.crm:
            await self._create_crm_note(
                mapping.amocrm_contact_id,
                f"📥 Входящее от {user_name}: {message_text[:200]}{'...' if len(message_text) > 200 else ''}"
            )
            return True, "Note created in CRM"

        return True, "No CRM action needed"


# Алиас для обратной совместимости
AmoCRMTelegramBridge = CRMTelegramBridge
