"""
AmoCRM API клиент
Интеграция с AmoCRM для работы с контактами и примечаниями
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import aiohttp

from src.config import settings
from src.logger import logger


class AmoCRMClient:
    """
    Клиент для работы с AmoCRM API
    Автоматическое обновление токенов
    """
    
    def __init__(self):
        self.domain = settings.AMOCRM_DOMAIN
        self.client_id = settings.AMOCRM_CLIENT_ID
        self.client_secret = settings.AMOCRM_CLIENT_SECRET
        self.redirect_uri = settings.AMOCRM_REDIRECT_URI
        
        self.access_token = settings.AMOCRM_ACCESS_TOKEN
        self.refresh_token = settings.AMOCRM_REFRESH_TOKEN
        self.token_expires_at = None
        if settings.AMOCRM_TOKEN_EXPIRES_AT:
            try:
                token_ts = settings.AMOCRM_TOKEN_EXPIRES_AT.replace("Z", "")
                self.token_expires_at = datetime.fromisoformat(token_ts)
            except ValueError:
                self.token_expires_at = None
        
        self.base_url = f'https://{self.domain}/api/v4'
        
        logger.info(f"🔗 AmoCRM клиент инициализирован для домена: {self.domain}")

    async def _save_tokens(self) -> None:
        try:
            from src.app_settings import update_settings_overrides
            values = {}
            if self.access_token:
                values["AMOCRM_ACCESS_TOKEN"] = self.access_token
            if self.refresh_token:
                values["AMOCRM_REFRESH_TOKEN"] = self.refresh_token
            if self.token_expires_at:
                values["AMOCRM_TOKEN_EXPIRES_AT"] = self.token_expires_at.isoformat()
            if values:
                _, errors = await update_settings_overrides(values)
                if errors:
                    logger.warning("⚠️ Ошибка сохранения AmoCRM токенов: %s", errors)
        except Exception as exc:
            logger.warning("⚠️ Не удалось сохранить AmoCRM токены: %s", exc)

    async def ensure_token_valid(self):
        """Проверка и обновление токена если необходимо"""
        if not self.access_token or not self.refresh_token:
            logger.warning("⚠️ Токены AmoCRM не настроены!")
            return False
        
        # Если токен истекает в течение 5 минут - обновляем
        if self.token_expires_at and datetime.now() > (self.token_expires_at - timedelta(minutes=5)):
            logger.info("🔄 Токен истекает, обновляем...")
            return await self.refresh_access_token()
        
        return True
    
    async def refresh_access_token(self) -> bool:
        """
        Обновление access токена через refresh token
        
        Returns:
            bool: Успешно ли обновлен токен
        """
        try:
            logger.info("🔄 Обновление AmoCRM access token...")
            
            async with aiohttp.ClientSession() as session:
                data = {
                    'client_id': self.client_id,
                    'client_secret': self.client_secret,
                    'grant_type': 'refresh_token',
                    'refresh_token': self.refresh_token,
                    'redirect_uri': self.redirect_uri,
                }
                
                async with session.post(
                    f'https://{self.domain}/oauth2/access_token',
                    json=data
                ) as response:
                    if response.status == 200:
                        tokens = await response.json()
                        
                        self.access_token = tokens['access_token']
                        self.refresh_token = tokens['refresh_token']
                        self.token_expires_at = datetime.now() + timedelta(seconds=tokens['expires_in'])
                        
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

    async def exchange_auth_code(self, code: str) -> bool:
        """
        Обмен authorization code на access/refresh токены.
        """
        try:
            logger.info("🔄 Обмен authorization code на токены AmoCRM...")
            async with aiohttp.ClientSession() as session:
                data = {
                    'client_id': self.client_id,
                    'client_secret': self.client_secret,
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': self.redirect_uri,
                }
                async with session.post(
                    f'https://{self.domain}/oauth2/access_token',
                    json=data
                ) as response:
                    if response.status == 200:
                        tokens = await response.json()
                        self.access_token = tokens['access_token']
                        self.refresh_token = tokens['refresh_token']
                        self.token_expires_at = datetime.now() + timedelta(seconds=tokens['expires_in'])
                        await self._save_tokens()
                        logger.info("✅ AmoCRM токены успешно получены")
                        return True
                    error_text = await response.text()
                    logger.error(f"❌ Ошибка OAuth обмена: {error_text}")
                    return False
        except Exception as e:
            logger.error(f"❌ Исключение при OAuth обмене: {e}")
            return False
    
    async def find_contact_by_phone(self, phone: str) -> Optional[Dict]:
        """
        Поиск контакта по номеру телефона
        
        Args:
            phone: Номер телефона
            
        Returns:
            Dict с данными контакта или None
        """
        if not await self.ensure_token_valid():
            return None
        
        try:
            logger.info(f"🔍 Поиск контакта в AmoCRM по телефону: {phone}")
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {self.access_token}',
                }
                params = {
                    'query': phone,
                }
                
                async with session.get(
                    f'{self.base_url}/contacts',
                    headers=headers,
                    params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        contacts = data.get('_embedded', {}).get('contacts', [])
                        
                        if contacts:
                            contact = contacts[0]
                            logger.info(
                                f"✅ Найден контакт: {contact.get('name')} "
                                f"(ID: {contact['id']})"
                            )
                            return contact
                        else:
                            logger.warning(f"⚠️ Контакт с телефоном {phone} не найден")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка поиска контакта: {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ Исключение при поиске контакта: {e}")
            return None
    
    async def find_contact_by_id(self, contact_id: int) -> Optional[Dict]:
        """
        Получение контакта по ID
        
        Args:
            contact_id: ID контакта в AmoCRM
            
        Returns:
            Dict с данными контакта или None
        """
        if not await self.ensure_token_valid():
            return None
        
        try:
            logger.info(f"🔍 Получение контакта ID: {contact_id}")
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {self.access_token}',
                }
                
                async with session.get(
                    f'{self.base_url}/contacts/{contact_id}',
                    headers=headers
                ) as response:
                    if response.status == 200:
                        contact = await response.json()
                        logger.info(f"✅ Контакт получен: {contact.get('name')}")
                        return contact
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка получения контакта: {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ Исключение при получении контакта: {e}")
            return None
    
    async def get_contact_field(self, contact_id: int, field_id: int) -> Optional[str]:
        """
        Получение значения custom поля контакта
        
        Args:
            contact_id: ID контакта
            field_id: ID custom поля
            
        Returns:
            Значение поля или None
        """
        contact = await self.find_contact_by_id(contact_id)
        if not contact:
            return None
        
        custom_fields = contact.get('custom_fields_values', [])
        for field in custom_fields:
            if field['field_id'] == field_id:
                values = field.get('values', [])
                if values:
                    return values[0].get('value')
        
        return None
    
    async def update_contact_field(
        self,
        contact_id: int,
        field_id: int,
        value: str
    ) -> bool:
        """
        Обновление custom поля контакта
        
        Args:
            contact_id: ID контакта
            field_id: ID custom поля
            value: Новое значение
            
        Returns:
            bool: Успешно ли обновлено
        """
        if not await self.ensure_token_valid():
            return False
        
        try:
            logger.info(
                f"📝 Обновление поля {field_id} контакта {contact_id} "
                f"на значение: {value}"
            )
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {self.access_token}',
                    'Content-Type': 'application/json',
                }
                
                data = {
                    'custom_fields_values': [
                        {
                            'field_id': field_id,
                            'values': [
                                {
                                    'value': value
                                }
                            ]
                        }
                    ]
                }
                
                async with session.patch(
                    f'{self.base_url}/contacts/{contact_id}',
                    headers=headers,
                    json=data
                ) as response:
                    if response.status == 200:
                        logger.info("✅ Поле успешно обновлено")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка обновления поля: {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"❌ Исключение при обновлении поля: {e}")
            return False
    
    async def create_note(
        self,
        contact_id: int,
        text: str,
        note_type: str = 'common'
    ) -> bool:
        """
        Создание примечания к контакту
        
        Args:
            contact_id: ID контакта
            text: Текст примечания
            note_type: Тип примечания ('common', 'call', etc.)
            
        Returns:
            bool: Успешно ли создано
        """
        if not await self.ensure_token_valid():
            return False
        
        try:
            logger.info(f"📝 Создание примечания для контакта {contact_id}")
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {self.access_token}',
                    'Content-Type': 'application/json',
                }
                
                data = [
                    {
                        'note_type': note_type,
                        'params': {
                            'text': f'📱 Telegram (MTProto): {text}'
                        }
                    }
                ]
                
                async with session.post(
                    f'{self.base_url}/contacts/{contact_id}/notes',
                    headers=headers,
                    json=data
                ) as response:
                    if response.status == 200:
                        logger.info("✅ Примечание создано")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка создания примечания: {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"❌ Исключение при создании примечания: {e}")
            return False
    
    async def get_task(self, task_id: int) -> Optional[Dict]:
        """
        Получение задачи по ID
        
        Args:
            task_id: ID задачи
            
        Returns:
            Dict с данными задачи или None
        """
        if not await self.ensure_token_valid():
            return None
        
        try:
            logger.info(f"🔍 Получение задачи ID: {task_id}")
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {self.access_token}',
                }
                
                async with session.get(
                    f'{self.base_url}/tasks/{task_id}',
                    headers=headers
                ) as response:
                    if response.status == 200:
                        task = await response.json()
                        logger.info("✅ Задача получена")
                        return task
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка получения задачи: {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ Исключение при получении задачи: {e}")
            return None
    
    async def complete_task(self, task_id: int) -> bool:
        """
        Завершение задачи
        
        Args:
            task_id: ID задачи
            
        Returns:
            bool: Успешно ли завершена
        """
        if not await self.ensure_token_valid():
            return False
        
        try:
            logger.info(f"✅ Завершение задачи ID: {task_id}")
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {self.access_token}',
                    'Content-Type': 'application/json',
                }
                
                data = {
                    'is_completed': True
                }
                
                async with session.patch(
                    f'{self.base_url}/tasks/{task_id}',
                    headers=headers,
                    json=data
                ) as response:
                    if response.status == 200:
                        logger.info("✅ Задача завершена")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка завершения задачи: {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"❌ Исключение при завершении задачи: {e}")
            return False
