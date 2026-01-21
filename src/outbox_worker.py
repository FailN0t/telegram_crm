"""
Outbox worker: processes queued messages and delivers them via Telegram.
"""

import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import select

from src.config import settings
from src.logger import logger
from src.database import init_db, SessionLocal, UiMessageHistory
from src.app_settings import refresh_settings_from_db
from src.observability import init_error_tracking
from src.telegram_manager import TelegramClientManager
from src.amocrm_client import AmoCRMClient
from src.bitrix24_client import Bitrix24Client
from src.bridge import CRMTelegramBridge
from src.outbox import (
    acquire_next_outbox,
    mark_outbox_result,
    mark_outbox_non_retryable
)


NON_RETRYABLE_ERRORS = (
    "user_not_found",
    "username_not_found",
    "phone_not_found",
    "missing_target",
    "amocrm is not configured",
    "bitrix24 is not configured",
    "crm is not configured",
    "contact_id is required",
    "task_id is required",
    "activity_id is required",
    "unknown_source",
)


def is_retryable_error(error_message: Optional[str]) -> bool:
    if not error_message:
        return True
    lowered = error_message.lower()
    return not any(token in lowered for token in NON_RETRYABLE_ERRORS)


class OutboxWorker:
    def __init__(self) -> None:
        self.telegram_manager: Optional[TelegramClientManager] = None
        self.crm = None  # CRM клиент (AmoCRM или Bitrix24)
        self.bridge: Optional[CRMTelegramBridge] = None
        self.stop_event = asyncio.Event()

    async def update_ui_history_status(
        self,
        db,
        payload: dict,
        status: str,
        error_message: Optional[str]
    ) -> None:
        if payload.get("source") != "ui":
            return

        chat_id = payload.get("chat_id")
        message_text = payload.get("message")
        if not chat_id or not message_text:
            return

        query = select(UiMessageHistory).filter_by(
            chat_id=chat_id,
            message_text=message_text,
            status="queued"
        )
        account_id = payload.get("account_id")
        if account_id:
            query = query.filter_by(account_id=account_id)
        result = await db.execute(
            query.order_by(UiMessageHistory.created_at.desc()).limit(1)
        )
        entry = result.scalars().first()
        if not entry:
            return

        entry.status = status
        entry.error_message = error_message
        entry.updated_at = datetime.utcnow()
        await db.commit()

    async def recover_orphaned_messages(self) -> None:
        """
        Fix #16: Recover orphaned messages from previous crashes.

        Finds messages stuck in 'processing' status and returns them to queue.
        This is called on startup to handle unclean shutdowns/crashes.
        """
        from src.database import SessionLocal, MessageOutbox
        from datetime import datetime, timedelta

        logger.info("🔍 Checking for orphaned messages from previous crashes...")

        async with SessionLocal() as session:
            # Find messages in 'processing' status older than 5 minutes
            timeout_threshold = datetime.utcnow() - timedelta(minutes=5)

            stmt = select(MessageOutbox).filter(
                MessageOutbox.status == "processing",
                MessageOutbox.updated_at < timeout_threshold
            )

            result = await session.execute(stmt)
            orphaned = result.scalars().all()

            if not orphaned:
                logger.info("✅ No orphaned messages found")
                return

            logger.warning(f"⚠️ Found {len(orphaned)} orphaned messages, returning to queue...")

            for outbox in orphaned:
                logger.info(
                    f"🔄 Recovering orphaned message: id={outbox.id} "
                    f"chat_id={outbox.chat_id} attempts={outbox.attempts}"
                )
                outbox.status = "failed"
                outbox.updated_at = datetime.utcnow()
                # Don't increment attempts - this wasn't a real delivery attempt
                # Schedule immediate retry
                outbox.next_attempt_at = datetime.utcnow()
                session.add(outbox)

            await session.commit()
            logger.info(f"✅ Recovered {len(orphaned)} orphaned messages")

    async def initialize(self) -> None:
        logger.info("📦 Инициализация outbox worker...")
        init_error_tracking()
        await init_db()
        try:
            await refresh_settings_from_db()
        except Exception as exc:
            logger.warning("⚠️ Не удалось применить admin-настройки: %s", exc)

        # Fix #16: Recover orphaned messages from previous crashes
        await self.recover_orphaned_messages()

        # Инициализация CRM клиента (AmoCRM или Bitrix24)
        crm_provider = settings.CRM_PROVIDER.lower()
        logger.info(f"🔗 CRM Provider: {crm_provider}")

        if crm_provider == "bitrix24":
            # Bitrix24 CRM
            if settings.BITRIX24_WEBHOOK_URL or (
                settings.BITRIX24_DOMAIN and settings.BITRIX24_ACCESS_TOKEN
            ):
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
                self.crm = AmoCRMClient()
                await self.crm.ensure_token_valid()
                logger.info("✅ AmoCRM клиент готов")
            else:
                self.crm = None
                logger.warning("⚠️ AmoCRM отключен: нет обязательных настроек")

        self.telegram_manager = TelegramClientManager()

        # Создаем bridge ДО запуска клиентов
        self.bridge = CRMTelegramBridge(self.telegram_manager, self.crm)

        # Устанавливаем bridge в telegram_manager
        await self.telegram_manager.set_bridge(self.bridge)  # Fix #123: await async method
        logger.info("✅ Bridge установлен в telegram_manager")

        # Теперь запускаем клиенты с уже установленным bridge
        await self.telegram_manager.start_all()

        logger.info("✅ Outbox worker готов")

    async def stop(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        if self.telegram_manager:
            await self.telegram_manager.stop_all()
        logger.info("🛑 Outbox worker остановлен")

    async def process_payload(self, db, payload: dict) -> Tuple[bool, str]:
        if not self.bridge or not self.telegram_manager:
            return False, "bridge_not_initialized"

        account_id = payload.get("account_id")
        if not account_id:
            account_id = await self.telegram_manager.get_default_account_id()

        source = payload.get("source")

        # API-запрос на отправку сообщения контакту CRM
        if source == "api":
            contact_id = payload.get("contact_id")
            if not contact_id:
                return False, "contact_id is required"
            return await self.bridge.send_message_from_crm(
                db,
                contact_id,
                payload.get("phone"),
                payload.get("username"),
                payload.get("message", ""),
                account_id=account_id
            )

        # AmoCRM webhook - задача на отправку
        if source == "amocrm_webhook":
            if not self.crm:
                return False, "amocrm is not configured"
            task_id = payload.get("task_id")
            if not task_id:
                return False, "task_id is required"
            return await self.bridge.handle_crm_task(db, task_id)

        # Bitrix24 webhook - активность на отправку
        if source == "bitrix24_webhook":
            if not self.crm:
                return False, "bitrix24 is not configured"
            activity_id = payload.get("activity_id")
            task_id = payload.get("task_id")
            if not activity_id and not task_id:
                return False, "activity_id or task_id is required"
            # Передаем в bridge - он определит что использовать
            return await self.bridge.handle_crm_task(
                db,
                task_id=task_id,
                activity_id=activity_id
            )

        # UI - прямая отправка из админки
        if source == "ui":
            if not account_id:
                return False, "account_id is required"
            client = await self.telegram_manager.get_client(account_id)
            target_user = None
            chat_id = payload.get("chat_id")
            if chat_id:
                target_user = await client.find_user_by_id(chat_id)
            if not target_user and payload.get("username"):
                target_user = await client.find_user_by_username(payload.get("username"))
            if not target_user and payload.get("phone"):
                target_user = await client.find_user_by_phone(payload.get("phone"))
            if not target_user:
                return False, "user_not_found"
            return await client.send_message_to_user(
                target_user,
                payload.get("message", ""),
                operator_id=payload.get("operator_id")
            )

        # Bitrix24 Open Lines - сообщение от оператора в Telegram
        if source == "bitrix24_openline":
            if not account_id:
                return False, "account_id is required"
            chat_id = payload.get("chat_id")
            message = payload.get("message", "")
            if not chat_id:
                return False, "chat_id is required"
            if not message:
                return False, "message is required"

            client = await self.telegram_manager.get_client(account_id)
            target_user = await client.find_user_by_id(chat_id)
            if not target_user:
                return False, "user_not_found"

            # Open Channels: пропускаем quiet hours, т.к. операторы отвечают в любое время
            success, result = await client.send_message_to_user(
                target_user,
                message,
                operator_id=payload.get("operator_id"),
                skip_quiet_hours=True
            )

            # Отправляем статусы доставки и прочтения обратно в Bitrix24
            if success and self.crm and hasattr(self.crm, 'send_status_delivery'):
                bitrix_msg_id = payload.get("bitrix_message_id")
                bitrix_chat_id = payload.get("bitrix_chat_id")
                line_id = payload.get("line_id", 0)

                if bitrix_msg_id and bitrix_chat_id:
                    try:
                        from src.config import settings

                        # Формат согласно официальной документации Bitrix24
                        messages = [{
                            "im": {
                                "chat_id": str(bitrix_chat_id),
                                "message_id": str(bitrix_msg_id)
                            },
                            "message": {
                                "id": str(bitrix_msg_id)
                            },
                            "chat": {
                                "id": str(chat_id)  # Telegram chat_id
                            }
                        }]

                        # Delivery status
                        delivery_result = await self.crm.send_status_delivery(
                            connector_id=settings.BITRIX24_CONNECTOR_ID,
                            line_id=line_id,
                            messages=messages
                        )
                        logger.info(f"✅ Delivery status: {delivery_result}")

                        # Reading status НЕ отправляем сразу
                        # Он будет отправлен при получении события MessageRead от Telegram
                        # См. обработчик в telegram_client.py: handle_message_read()

                    except Exception as e:
                        logger.warning(f"⚠️ Не удалось отправить статусы: {e}")
                        import traceback
                        logger.warning(traceback.format_exc())
                else:
                    if not bitrix_msg_id:
                        logger.warning(f"⚠️ bitrix_message_id отсутствует в payload")
                    if not bitrix_chat_id:
                        logger.warning(f"⚠️ bitrix_chat_id отсутствует в payload")

            return success, result

        return False, "unknown_source"

    async def run(self) -> None:
        await self.initialize()
        logger.info("▶️ Outbox worker запущен")

        while not self.stop_event.is_set():
            outbox = None
            session = None
            try:
                async with SessionLocal() as session:
                    outbox = await acquire_next_outbox(session)
                    if not outbox:
                        await asyncio.sleep(settings.OUTBOX_POLL_INTERVAL)
                        continue

                    # Проверяем stop_event после acquire, но до обработки
                    if self.stop_event.is_set():
                        logger.warning(
                            "⚠️ Stop event установлен, возвращаем сообщение в очередь: id=%s",
                            outbox.id
                        )
                        # Возвращаем сообщение в очередь, отменяя acquire
                        await mark_outbox_result(session, outbox, False, "worker_shutdown")
                        break

                    logger.info(
                        "📤 Отправка из outbox: id=%s source=%s attempts=%s",
                        outbox.id,
                        outbox.payload.get("source"),
                        outbox.attempts
                    )

                    payload = dict(outbox.payload or {})
                    if outbox.account_id and "account_id" not in payload:
                        payload["account_id"] = outbox.account_id

                    # Fix #15: Process with timeout to handle graceful shutdown
                    success, message = await self.process_payload(session, payload)

                    # Fix #15: Check if shutdown requested during processing
                    if self.stop_event.is_set():
                        logger.warning(
                            "⚠️ Shutdown requested during processing, saving result for id=%s",
                            outbox.id
                        )
                        # Continue to save result, then exit

                    if success:
                        await mark_outbox_result(session, outbox, True, None)
                        await self.update_ui_history_status(
                            session,
                            outbox.payload,
                            "sent",
                            None
                        )
                    else:
                        if is_retryable_error(message):
                            await mark_outbox_result(session, outbox, False, message)
                            await self.update_ui_history_status(
                                session,
                                outbox.payload,
                                "failed",
                                message
                            )
                        else:
                            await mark_outbox_non_retryable(session, outbox, message)
                            await self.update_ui_history_status(
                                session,
                                outbox.payload,
                                "failed",
                                message
                            )

            except Exception as exc:
                logger.error(f"❌ Ошибка обработки outbox: {exc}")
                # КРИТИЧНО: Если произошла ошибка И у нас есть outbox,
                # помечаем его как failed чтобы не потерять сообщение
                # Fix #175: Create NEW session since old one is closed after async with block
                if outbox:
                    try:
                        async with SessionLocal() as error_session:
                            await mark_outbox_result(error_session, outbox, False, f"exception: {str(exc)[:200]}")
                            await self.update_ui_history_status(
                                error_session,
                                outbox.payload,
                                "failed",
                                str(exc)[:200]
                            )
                    except Exception as mark_exc:
                        logger.error(f"❌ Не удалось пометить outbox как failed: {mark_exc}")

        # Fix #15: Log graceful shutdown completion
        logger.info("✅ Graceful shutdown complete: all in-progress messages saved")
        await self.stop()


worker = OutboxWorker()


def handle_signal(signum, frame):
    logger.info(f"⚠️ Получен сигнал {signum}, завершаем работу...")
    worker.stop_event.set()


async def main() -> None:
    Path("logs").mkdir(exist_ok=True)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        await worker.run()
    except KeyboardInterrupt:
        await worker.stop()
    except Exception as exc:
        logger.critical(f"💥 Необработанная ошибка worker: {exc}")
        await worker.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
