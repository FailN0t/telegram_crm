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
from src.app_settings import refresh_settings_from_db
from src.observability import init_error_tracking
from src.telegram_manager import TelegramClientManager
from src.amocrm_client import AmoCRMClient
from src.bitrix24_client import Bitrix24Client
from src.bridge import CRMTelegramBridge
from src.api_server import app, set_bridge


class Application:
    """Главное приложение"""

    def __init__(self):
        self.telegram_manager = None
        self.crm = None  # CRM клиент (AmoCRM или Bitrix24)
        self.bridge = None
        self.api_server_task = None
        self.telegram_tasks = []
        self.running = False
        self.stop_event = asyncio.Event()

        logger.info(f"🚀 Инициализация {settings.APP_NAME} v{settings.APP_VERSION}")
    
    async def initialize(self):
        """Инициализация всех компонентов"""
        try:
            logger.info("🔧 Инициализация компонентов...")
            init_error_tracking()
            
            # 1. Инициализация БД
            logger.info("📊 Инициализация базы данных...")
            await init_db()
            try:
                await refresh_settings_from_db()
            except Exception as exc:
                logger.warning("⚠️ Не удалось применить admin-настройки: %s", exc)
            logger.info("✅ База данных готова")
            
            # 2. Инициализация CRM клиента (AmoCRM или Bitrix24)
            crm_provider = settings.CRM_PROVIDER.lower()
            logger.info(f"🔗 CRM Provider: {crm_provider}")

            if crm_provider == "bitrix24":
                # Bitrix24 CRM
                if settings.BITRIX24_WEBHOOK_URL or (
                    settings.BITRIX24_DOMAIN and settings.BITRIX24_ACCESS_TOKEN
                ):
                    logger.info("🔗 Инициализация Bitrix24 клиента...")
                    self.crm = Bitrix24Client()
                    logger.info("✅ Bitrix24 клиент готов")
                else:
                    self.crm = None
                    logger.warning(
                        "⚠️ Bitrix24 отключен: нет BITRIX24_WEBHOOK_URL "
                        "или BITRIX24_DOMAIN + BITRIX24_ACCESS_TOKEN"
                    )
            else:
                # AmoCRM (default)
                if (
                    settings.AMOCRM_DOMAIN
                    and settings.AMOCRM_CLIENT_ID
                    and settings.AMOCRM_CLIENT_SECRET
                    and settings.AMOCRM_REDIRECT_URI
                ):
                    logger.info("🔗 Инициализация AmoCRM клиента...")
                    self.crm = AmoCRMClient()

                    # Проверяем токены
                    if await self.crm.ensure_token_valid():
                        logger.info("✅ AmoCRM клиент готов")
                    else:
                        logger.warning("⚠️ Токены AmoCRM не настроены или невалидны")
                else:
                    self.crm = None
                    logger.warning("⚠️ AmoCRM отключен: нет обязательных настроек")
            
            if settings.OUTBOX_PROCESS_INLINE:
                # 3. Инициализация Telegram manager (без запуска клиентов)
                logger.info("📱 Инициализация Telegram manager...")
                self.telegram_manager = TelegramClientManager()
                logger.info("✅ Telegram manager создан")

                # 4. Создание Bridge (ДО запуска клиентов!)
                logger.info("🌉 Создание Bridge...")
                self.bridge = CRMTelegramBridge(self.telegram_manager, self.crm)

                # Устанавливаем bridge в API сервере и TelegramClientManager
                set_bridge(self.bridge)
                await self.telegram_manager.set_bridge(self.bridge)  # Fix #123: await async method
                logger.info("✅ Bridge установлен в telegram_manager")

                # 5. Запуск Telegram клиентов (с уже установленным bridge!)
                logger.info("📱 Запуск Telegram клиентов с установленным bridge...")
                await self.telegram_manager.start_all()
                logger.info(f"✅ Telegram клиенты готовы (clients count: {len(self.telegram_manager._clients)})")
            else:
                logger.warning(
                    "⚠️ OUTBOX_PROCESS_INLINE=False: Telegram клиент не "
                    "инициализируется в API сервере. "
                    "Запустите outbox_worker для доставки."
                )
                self.telegram_manager = None
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
            if self.telegram_manager:
                self.telegram_tasks = self.telegram_manager.get_run_tasks()
            
            logger.info("✅ Приложение запущено!")
            logger.info("📊 Статистика доступна на: /api/stats")
            logger.info("🏥 Health check: /health")
            logger.info("📚 API документация: /docs" if settings.DEBUG else "")
            
            # Ждем завершения задач
            tasks = [self.api_server_task]
            if self.telegram_tasks:
                tasks.extend(self.telegram_tasks)
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
            if self.telegram_manager:
                logger.info("📱 Остановка Telegram клиентов...")
                await self.telegram_manager.stop_all()

            # Отменяем задачи
            for task in self.telegram_tasks:
                if task and not task.done():
                    task.cancel()
            
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

    # Устанавливаем флаг остановки (безопасно из синхронного контекста)
    application.stop_event.set()


async def main():
    """Главная функция"""

    # Создаем директории если их нет
    Path("logs").mkdir(exist_ok=True)

    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        # Запускаем приложение в фоновой задаче
        app_task = asyncio.create_task(application.start())

        # Ждем сигнала остановки или завершения приложения
        done, pending = await asyncio.wait(
            [app_task, asyncio.create_task(application.stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Если получен сигнал остановки
        if application.stop_event.is_set():
            logger.info("🛑 Получен сигнал остановки, graceful shutdown...")

            # Останавливаем приложение с таймаутом
            try:
                await asyncio.wait_for(application.stop(), timeout=30.0)
                logger.info("✅ Graceful shutdown завершен успешно")
            except asyncio.TimeoutError:
                logger.error("❌ Shutdown timeout (30s), принудительный выход")
                # Отменяем все pending задачи
                for task in pending:
                    task.cancel()

            # Отменяем app_task если он еще работает
            if not app_task.done():
                app_task.cancel()
                try:
                    await app_task
                except asyncio.CancelledError:
                    pass

    except KeyboardInterrupt:
        logger.info("⌨️  Остановка по Ctrl+C")
        try:
            await asyncio.wait_for(application.stop(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.error("❌ Shutdown timeout")
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
