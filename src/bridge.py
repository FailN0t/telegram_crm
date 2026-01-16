"""
Bridge между AmoCRM и Telegram
Основная бизнес-логика интеграции
"""

from typing import Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.telegram_client import MTProtoClient
from src.amocrm_client import AmoCRMClient
from src.database import ChatMapping, MessageHistory
from src.config import settings
from src.logger import logger


class AmoCRMTelegramBridge:
    """
    Мост между AmoCRM и Telegram
    Координирует работу обоих клиентов
    """
    
    def __init__(self, telegram: MTProtoClient, amocrm: Optional[AmoCRMClient]):
        self.telegram = telegram
        self.amocrm = amocrm
        logger.info("🌉 Bridge инициализирован")
    
    async def send_message_from_amocrm(
        self,
        db: AsyncSession,
        contact_id: int,
        phone: Optional[str],
        username: Optional[str],
        message: str
    ) -> Tuple[bool, str]:
        """
        Отправка сообщения клиенту из AmoCRM
        
        Args:
            db: Сессия БД
            contact_id: ID контакта в AmoCRM
            phone: Номер телефона (опционально)
            username: Username в Telegram (опционально)
            message: Текст сообщения
            
        Returns:
            (success, message): Результат отправки
        """
        if not self.amocrm:
            return False, "AmoCRM is not configured"

        logger.info(
            f"📤 Запрос на отправку сообщения: "
            f"contact_id={contact_id}, phone={phone}, username={username}"
        )
        
        # Проверяем согласие клиента
        if settings.AMOCRM_FIELD_TELEGRAM_CONSENT:
            has_consent = await self.amocrm.get_contact_field(
                contact_id,
                settings.AMOCRM_FIELD_TELEGRAM_CONSENT
            )
            
            if not has_consent or has_consent.lower() != 'true':
                error_msg = "Клиент не дал согласия на контакт через Telegram"
                logger.error(f"❌ {error_msg}")
                await self.amocrm.create_note(contact_id, f"❌ {error_msg}")
                return False, error_msg
        
        # Проверяем, есть ли уже связь в БД
        result = await db.execute(
            select(ChatMapping).filter_by(amocrm_contact_id=contact_id)
        )
        mapping = result.scalars().first()
        
        user = None
        
        if mapping and mapping.telegram_chat_id:
            # Есть связь - получаем пользователя по chat_id
            try:
                user = await self.telegram.client.get_entity(mapping.telegram_chat_id)
                logger.info(f"✅ Найден по сохраненному chat_id: {mapping.telegram_chat_id}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось получить по chat_id: {e}")
                user = None
        
        # Если нет в БД или не удалось получить - ищем
        if not user:
            # Сначала пробуем по username (быстрее и надежнее)
            if username:
                user = await self.telegram.find_user_by_username(username)
            
            # Если не нашли, пробуем по телефону
            if not user and phone:
                user = await self.telegram.find_user_by_phone(phone)
        
        if not user:
            error_msg = "Пользователь не найден в Telegram"
            logger.error(f"❌ {error_msg}")
            await self.amocrm.create_note(contact_id, f"❌ {error_msg}")
            return False, error_msg
        
        # Определяем, первое ли это сообщение
        is_new_chat = not mapping or not mapping.telegram_chat_id
        
        # Отправляем сообщение
        success, result = await self.telegram.send_message_to_user(
            user,
            message,
            is_new_chat
        )
        
        if success:
            # Сохраняем/обновляем связь в БД
            if not mapping:
                mapping = ChatMapping(
                    telegram_chat_id=user.id,
                    telegram_username=user.username,
                    telegram_first_name=user.first_name,
                    telegram_last_name=user.last_name,
                    phone_number=phone,
                    amocrm_contact_id=contact_id,
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
                chat_mapping_id=mapping.id,
                amocrm_contact_id=contact_id,
                direction='outbound',
                message_text=message,
                message_type='text',
                telegram_chat_id=user.id,
                status='sent'
            )
            db.add(history)
            await db.commit()
            
            # Обновляем поле chat_id в AmoCRM (если настроено)
            if settings.AMOCRM_FIELD_TELEGRAM_CHAT_ID:
                await self.amocrm.update_contact_field(
                    contact_id,
                    settings.AMOCRM_FIELD_TELEGRAM_CHAT_ID,
                    str(user.id)
                )
            
            # Создаем примечание в AmoCRM
            await self.amocrm.create_note(
                contact_id,
                f"✅ Отправлено: {message[:100]}{'...' if len(message) > 100 else ''}"
            )
            
            logger.info(f"✅ Сообщение успешно отправлено и сохранено")
            
        else:
            # Создаем примечание об ошибке
            await self.amocrm.create_note(
                contact_id,
                f"❌ Ошибка отправки: {result}"
            )
            
            # Если FloodWait - сохраняем в БД для повторной отправки
            if "FloodWait" in result:
                history = MessageHistory(
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
    
    async def handle_amocrm_task(
        self,
        db: AsyncSession,
        task_id: int
    ) -> Tuple[bool, str]:
        """
        Обработка задачи из AmoCRM
        
        Args:
            db: Сессия БД
            task_id: ID задачи
            
        Returns:
            (success, message): Результат обработки
        """
        if not self.amocrm:
            return False, "AmoCRM is not configured"

        logger.info(f"📋 Обработка задачи AmoCRM: {task_id}")
        
        # Получаем задачу
        task = await self.amocrm.get_task(task_id)
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
        contact = await self.amocrm.find_contact_by_id(contact_id)
        if not contact:
            return False, "Контакт не найден"
        
        # Извлекаем телефон и username
        phone = None
        username = None
        
        # Ищем телефон в контакте
        custom_fields = contact.get('custom_fields_values', [])
        for field in custom_fields:
            if field['field_code'] == 'PHONE':
                values = field.get('values', [])
                if values:
                    phone = values[0].get('value')
            elif field['field_id'] == settings.AMOCRM_FIELD_TELEGRAM_USERNAME:
                values = field.get('values', [])
                if values:
                    username = values[0].get('value')
        
        # Отправляем сообщение
        success, result = await self.send_message_from_amocrm(
            db,
            contact_id,
            phone,
            username,
            task_text
        )
        
        # Если успешно - завершаем задачу
        if success:
            await self.amocrm.complete_task(task_id)
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
        
        return {
            "telegram": self.telegram.get_stats(),
            "mappings": {
                "total": total_mappings,
                "active": active_mappings,
            },
            "messages": {
                "total": total_messages,
            }
        }
