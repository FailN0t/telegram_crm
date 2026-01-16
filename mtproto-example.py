"""
Упрощенный пример MTProto клиента для AmoCRM
Версия для быстрого старта и тестирования
"""

import os
import asyncio
import logging
from telethon import TelegramClient
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact
from telethon.errors import FloodWaitError, UserPrivacyRestrictedError
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
API_ID = int(os.getenv('TELEGRAM_API_ID', '0'))
API_HASH = os.getenv('TELEGRAM_API_HASH', '')
PHONE = os.getenv('TELEGRAM_PHONE', '')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создаем клиент
client = TelegramClient('session', API_ID, API_HASH)


async def find_user_by_phone(phone: str):
    """Поиск пользователя по номеру телефона"""
    try:
        # Нормализуем номер
        if not phone.startswith('+'):
            phone = '+' + phone
        
        logger.info(f"🔍 Поиск пользователя по номеру {phone}")
        
        # Импортируем контакт
        result = await client(ImportContactsRequest([
            InputPhoneContact(
                client_id=0,
                phone=phone,
                first_name="Contact",
                last_name=""
            )
        ]))
        
        if result.users:
            user = result.users[0]
            logger.info(f"✅ Найден: {user.first_name} (@{user.username or user.id})")
            return user
        else:
            logger.warning(f"⚠️ Пользователь не найден или скрыл номер")
            return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return None


async def find_user_by_username(username: str):
    """Поиск пользователя по username"""
    try:
        username = username.lstrip('@')
        logger.info(f"🔍 Поиск пользователя @{username}")
        
        user = await client.get_entity(username)
        logger.info(f"✅ Найден: {user.first_name} (@{user.username})")
        return user
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return None


async def send_message(user, message: str):
    """Отправка сообщения пользователю"""
    try:
        logger.info(f"📤 Отправка сообщения...")
        
        await client.send_message(user, message)
        
        logger.info(f"✅ Сообщение успешно отправлено!")
        return True
        
    except FloodWaitError as e:
        logger.error(f"🚫 FloodWait: нужно подождать {e.seconds} секунд")
        logger.error(f"⚠️ ВЫ ОТПРАВЛЯЕТЕ СЛИШКОМ МНОГО СООБЩЕНИЙ!")
        return False
        
    except UserPrivacyRestrictedError:
        logger.error(f"🔒 Пользователь запретил сообщения от незнакомцев")
        return False
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False


async def main():
    """Главная функция"""
    
    # Проверка конфигурации
    if not API_ID or not API_HASH or not PHONE:
        print("❌ Ошибка: Заполните .env файл!")
        print("Необходимо указать:")
        print("  - TELEGRAM_API_ID")
        print("  - TELEGRAM_API_HASH")
        print("  - TELEGRAM_PHONE")
        return
    
    logger.info("🚀 Запуск MTProto клиента...")
    
    # Подключаемся
    await client.start(phone=PHONE)
    
    # Получаем информацию о себе
    me = await client.get_me()
    logger.info(f"✅ Авторизован как: {me.first_name} (@{me.username})")
    logger.info(f"📱 Телефон: {me.phone}")
    
    print("\n" + "="*50)
    print("ТЕСТОВЫЙ РЕЖИМ")
    print("="*50 + "\n")
    
    # Пример 1: Поиск по username
    print("1️⃣ Тест поиска по username:")
    test_username = input("Введите username для поиска (или Enter для пропуска): ").strip()
    if test_username:
        user = await find_user_by_username(test_username)
        
        if user:
            confirm = input(f"Отправить тестовое сообщение @{user.username}? (yes/no): ")
            if confirm.lower() == 'yes':
                message = "Привет! Это тестовое сообщение от AmoCRM интеграции."
                await send_message(user, message)
    
    print()
    
    # Пример 2: Поиск по телефону
    print("2️⃣ Тест поиска по номеру телефона:")
    test_phone = input("Введите номер (с +, например +79991234567, или Enter для пропуска): ").strip()
    if test_phone:
        user = await find_user_by_phone(test_phone)
        
        if user:
            confirm = input(f"Отправить тестовое сообщение? (yes/no): ")
            if confirm.lower() == 'yes':
                message = "Здравствуйте! Это тестовое сообщение от AmoCRM интеграции."
                await send_message(user, message)
    
    print("\n" + "="*50)
    print("✅ Тестирование завершено!")
    print("="*50)
    
    # Отключаемся
    await client.disconnect()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Остановлено пользователем")
    except Exception as e:
        logger.critical(f"💥 Критическая ошибка: {e}")
        raise

