"""
Главное приложение
Точка входа, инициализация всех компонентов
"""

import asyncio
import signal
import sys
from pathlib import Path

import uvicorn
from src.config import settings
from src.logger import logger
from src.database import init_db
from src.observability import init_error_tracking
from src.telegram_client import MTProtoClient
from src.amocrm_client import AmoCRMClient
from src.bridge import AmoCRMTelegramBridge
from src.api_server import app, set_bridge


class Application:
    """Главное приложение"""
    
    def __init__(self):
        self.telegram = None
        self.amocrm = None
        self.bridge = None
        self.api_server_task = None
        self.telegram_task = None
        self.running = False
        
        logger.info(f"🚀 Инициализация {settings.APP_NAME} v{settings.APP_VERSION}")
    
    async def initialize(self):
        """Инициализация всех компонентов"""
        try:
            logger.info("🔧 Инициализация компонентов...")
            init_error_tracking()
            
            # 1. Инициализация БД
            logger.info("📊 Инициализация базы данных...")
            await init_db()
            logger.info("✅ База данных готова")
            
            # 2. Инициализация AmoCRM клиента (опционально)
            if (
                settings.AMOCRM_DOMAIN
                and settings.AMOCRM_CLIENT_ID
                and settings.AMOCRM_CLIENT_SECRET
                and settings.AMOCRM_REDIRECT_URI
            ):
                logger.info("🔗 Инициализация AmoCRM клиента...")
                self.amocrm = AmoCRMClient()
                
                # Проверяем токены
                if await self.amocrm.ensure_token_valid():
                    logger.info("✅ AmoCRM клиент готов")
                else:
                    logger.warning("⚠️ Токены AmoCRM не настроены или невалидны")
            else:
                self.amocrm = None
                logger.warning("⚠️ AmoCRM отключен: нет обязательных настроек")
            
            if settings.OUTBOX_PROCESS_INLINE:
                # 3. Инициализация Telegram клиента
                logger.info("📱 Инициализация Telegram клиента...")
                self.telegram = MTProtoClient()
                await self.telegram.start()
                logger.info("✅ Telegram клиент готов")

                # 4. Создание Bridge
                logger.info("🌉 Создание Bridge...")
                self.bridge = AmoCRMTelegramBridge(self.telegram, self.amocrm)

                # Устанавливаем bridge в API сервере
                set_bridge(self.bridge)
                logger.info("✅ Bridge готов")
            else:
                logger.warning(
                    "⚠️ OUTBOX_PROCESS_INLINE=False: Telegram клиент не "
                    "инициализируется в API сервере. "
                    "Запустите outbox_worker для доставки."
                )
                self.telegram = None
                self.bridge = None
                set_bridge(None)
            
            logger.info("✅ Все компоненты инициализированы!")
            
        except Exception as e:
            logger.critical(f"💥 Критическая ошибка инициализации: {e}")
            raise
    
    async def start_api_server(self):
        """Запуск API сервера"""
        try:
            logger.info(
                f"🌐 Запуск API сервера на "
                f"{settings.API_HOST}:{settings.API_PORT}..."
            )
            
            config = uvicorn.Config(
                app,
                host=settings.API_HOST,
                port=settings.API_PORT,
                log_level=settings.LOG_LEVEL.lower(),
                access_log=settings.DEBUG
            )
            server = uvicorn.Server(config)
            await server.serve()
            
        except Exception as e:
            logger.error(f"❌ Ошибка API сервера: {e}")
            raise
    
    async def start(self):
        """Запуск приложения"""
        self.running = True
        
        try:
            # Инициализация
            await self.initialize()
            
            # Запускаем API сервер в отдельной задаче
            self.api_server_task = asyncio.create_task(self.start_api_server())
            
            # Запускаем Telegram клиент в отдельной задаче
            if self.telegram:
                self.telegram_task = asyncio.create_task(self.telegram.run())
            
            logger.info("✅ Приложение запущено!")
            logger.info("📊 Статистика доступна на: /api/stats")
            logger.info("🏥 Health check: /health")
            logger.info("📚 API документация: /docs" if settings.DEBUG else "")
            
            # Ждем завершения задач
            tasks = [self.api_server_task]
            if self.telegram_task:
                tasks.append(self.telegram_task)
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            logger.critical(f"💥 Критическая ошибка: {e}")
            await self.stop()
            raise
    
    async def stop(self):
        """Остановка приложения"""
        if not self.running:
            return
        
        logger.info("🛑 Остановка приложения...")
        self.running = False
        
        try:
            # Останавливаем Telegram клиент
            if self.telegram:
                logger.info("📱 Остановка Telegram клиента...")
                await self.telegram.stop()
            
            # Отменяем задачи
            if self.telegram_task and not self.telegram_task.done():
                self.telegram_task.cancel()
            
            if self.api_server_task and not self.api_server_task.done():
                self.api_server_task.cancel()
            
            logger.info("✅ Приложение остановлено")
            
        except Exception as e:
            logger.error(f"❌ Ошибка при остановке: {e}")


# Глобальный экземпляр приложения
application = Application()


def handle_signal(signum, frame):
    """Обработка сигналов (Ctrl+C, etc.)"""
    logger.info(f"⚠️ Получен сигнал {signum}")
    
    # Создаем задачу остановки
    asyncio.create_task(application.stop())


async def main():
    """Главная функция"""
    
    # Создаем директории если их нет
    Path("logs").mkdir(exist_ok=True)
    
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    try:
        await application.start()
    except KeyboardInterrupt:
        logger.info("⌨️  Остановка по Ctrl+C")
        await application.stop()
    except Exception as e:
        logger.critical(f"💥 Необработанная ошибка: {e}")
        await application.stop()
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Завершение работы")
    except Exception as e:
        logger.critical(f"💥 Критическая ошибка: {e}")
        sys.exit(1)
