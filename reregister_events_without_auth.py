#!/usr/bin/env python3
"""
Переустановка событий Bitrix24 без auth_type
"""
import asyncio
from src.config import settings
from src.database import init_db
from src.bitrix24_client import Bitrix24Client
from src.logger import logger


async def reregister_events():
    """Переустановка событий без auth_type параметра"""

    webhook_url = "https://your-server.example.com/api/webhook/bitrix24/openlines"

    logger.info("🔧 Инициализация...")
    await init_db()

    # Load app settings from database first
    logger.info("📥 Загрузка настроек из БД...")
    from src.app_settings import refresh_settings_from_db
    try:
        await refresh_settings_from_db()
        logger.info("✅ Настройки загружены")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось загрузить настройки: {e}")

    logger.info("🔧 Инициализация Bitrix24 клиента...")
    client = Bitrix24Client()

    # Загрузка токенов
    logger.info("🔑 Загрузка токенов...")
    token_valid = await client.ensure_token_valid()
    if not token_valid:
        logger.error("❌ Не удалось загрузить токены")
        return False

    # 1. Удалить все старые события
    logger.info(f"🗑️ Удаление старых событий...")
    result = await client.unregister_open_line_events(webhook_url)
    logger.info(f"Результат удаления: {result}")

    # 2. Зарегистрировать заново БЕЗ auth_type
    logger.info(f"📝 Регистрация событий БЕЗ auth_type...")

    events = [
        "ONIMCONNECTORMESSAGEADD",
        "ONIMCONNECTORLINEJOIN",  # Может и не нужен, но попробуем
        "ONIMCONNECTORLINEDELETE",
        "ONIMCONNECTORMESSAGEUPDATE",
        "ONIMCONNECTORMESSAGEDELETE"
    ]

    results = {}
    for event in events:
        logger.info(f"  Регистрация {event}...")

        # Вызываем event.bind БЕЗ параметра auth_type
        result = await client._call_method("event.bind", {
            "event": event,
            "handler": webhook_url
            # auth_type НЕ передаём - пусть Bitrix24 сам выберет
        })

        if result and result.get("result"):
            results[event] = True
            logger.info(f"  ✅ {event} зарегистрирован")
        else:
            results[event] = False
            error = result.get("error_description") if result else "Unknown error"
            logger.warning(f"  ❌ {event} не зарегистрирован: {error}")

    # 3. Проверка
    logger.info("🔍 Проверка зарегистрированных событий...")
    all_events = await client.get_registered_events()

    open_line_events = [
        e for e in all_events
        if e.get('event', '').startswith('ONIMCONNECTOR')
    ]

    logger.info(f"✅ Зарегистрировано Open Line событий: {len(open_line_events)}")
    for event in open_line_events:
        logger.info(f"  ✓ {event.get('event')}: auth_type={event.get('auth_type', 'не указан')}")

    return len(open_line_events) > 0


if __name__ == "__main__":
    import sys
    try:
        success = asyncio.run(reregister_events())
        if success:
            logger.info("✅ События успешно переустановлены!")
            sys.exit(0)
        else:
            logger.error("❌ Не удалось переустановить события")
            sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
