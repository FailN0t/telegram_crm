#!/usr/bin/env python3
"""
Скрипт для исправления регистрации событий Bitrix24 Open Channels
1. Удаляет все старые обработчики событий
2. Регистрирует новые с правильным URL
"""
import asyncio
import sys
from src.config import settings
from src.bitrix24_client import Bitrix24Client
from src.logger import logger


async def fix_events():
    """Удаление старых и регистрация новых событий"""

    webhook_url = "https://your-server.example.com/api/webhook/bitrix24/openlines"

    logger.info("🔧 Инициализация Bitrix24 клиента...")
    from src.database import init_db
    await init_db()

    client = Bitrix24Client()

    # Загрузка токенов из БД
    logger.info("🔑 Загрузка токенов из БД...")
    token_valid = await client.ensure_token_valid()
    if not token_valid:
        logger.error("❌ Не удалось загрузить токены из БД")
        return False
    logger.info("✅ Токены загружены")

    # 1. Получить список всех зарегистрированных событий
    logger.info("📋 Получение списка зарегистрированных событий...")
    events = await client.get_registered_events()

    logger.info(f"📊 Найдено {len(events)} событий")
    for event in events:
        event_name = event.get('event', 'unknown')
        handler = event.get('handler', 'unknown')
        logger.info(f"  - {event_name}: {handler}")

    # 2. Удалить все Open Line события
    logger.info(f"🗑️ Удаление старых обработчиков...")
    result = await client.unregister_open_line_events(webhook_url)
    logger.info(f"✅ Результат удаления: {result}")

    # 3. Зарегистрировать события заново
    logger.info(f"📝 Регистрация новых обработчиков на {webhook_url}...")
    result = await client.register_open_line_events(webhook_url)
    logger.info(f"✅ Результат регистрации: {result}")

    # 4. Проверка
    logger.info("🔍 Проверка зарегистрированных событий...")
    events_after = await client.get_registered_events()
    open_line_events = [
        e for e in events_after
        if e.get('event', '').startswith('ONIMCONNECTOR')
    ]

    logger.info(f"✅ Зарегистрировано Open Line событий: {len(open_line_events)}")
    for event in open_line_events:
        logger.info(f"  ✓ {event.get('event')}: {event.get('handler')}")

    return len(open_line_events) > 0


if __name__ == "__main__":
    try:
        success = asyncio.run(fix_events())
        if success:
            logger.info("✅ События успешно настроены!")
            sys.exit(0)
        else:
            logger.error("❌ Не удалось настроить события")
            sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Ошибка: {e}")
        sys.exit(1)
