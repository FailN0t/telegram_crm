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
from src.observability import init_error_tracking
from src.telegram_client import MTProtoClient
from src.amocrm_client import AmoCRMClient
from src.bridge import AmoCRMTelegramBridge
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
    "contact_id is required",
    "task_id is required",
    "unknown_source",
)


def is_retryable_error(error_message: Optional[str]) -> bool:
    if not error_message:
        return True
    lowered = error_message.lower()
    return not any(token in lowered for token in NON_RETRYABLE_ERRORS)


class OutboxWorker:
    def __init__(self) -> None:
        self.telegram: Optional[MTProtoClient] = None
        self.amocrm: Optional[AmoCRMClient] = None
        self.bridge: Optional[AmoCRMTelegramBridge] = None
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

        result = await db.execute(
            select(UiMessageHistory)
            .filter_by(chat_id=chat_id, message_text=message_text, status="queued")
            .order_by(UiMessageHistory.created_at.desc())
            .limit(1)
        )
        entry = result.scalars().first()
        if not entry:
            return

        entry.status = status
        entry.error_message = error_message
        entry.updated_at = datetime.utcnow()
        await db.commit()

    async def initialize(self) -> None:
        logger.info("📦 Инициализация outbox worker...")
        init_error_tracking()
        await init_db()

        if (
            settings.AMOCRM_DOMAIN
            and settings.AMOCRM_CLIENT_ID
            and settings.AMOCRM_CLIENT_SECRET
            and settings.AMOCRM_REDIRECT_URI
        ):
            self.amocrm = AmoCRMClient()
            await self.amocrm.ensure_token_valid()
        else:
            self.amocrm = None
            logger.warning("⚠️ AmoCRM отключен: нет обязательных настроек")

        self.telegram = MTProtoClient()
        await self.telegram.start()

        self.bridge = AmoCRMTelegramBridge(self.telegram, self.amocrm)
        logger.info("✅ Outbox worker готов")

    async def stop(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        if self.telegram:
            await self.telegram.stop()
        logger.info("🛑 Outbox worker остановлен")

    async def process_payload(self, db, payload: dict) -> Tuple[bool, str]:
        if not self.bridge or not self.telegram:
            return False, "bridge_not_initialized"

        source = payload.get("source")
        if source == "api":
            contact_id = payload.get("contact_id")
            if not contact_id:
                return False, "contact_id is required"
            return await self.bridge.send_message_from_amocrm(
                db,
                contact_id,
                payload.get("phone"),
                payload.get("username"),
                payload.get("message", "")
            )

        if source == "amocrm_webhook":
            if not self.bridge:
                return False, "bridge_not_initialized"
            if not self.amocrm:
                return False, "amocrm is not configured"
            task_id = payload.get("task_id")
            if not task_id:
                return False, "task_id is required"
            return await self.bridge.handle_amocrm_task(db, task_id)

        if source == "ui":
            target_user = None
            chat_id = payload.get("chat_id")
            if chat_id:
                target_user = await self.telegram.find_user_by_id(chat_id)
            if not target_user and payload.get("username"):
                target_user = await self.telegram.find_user_by_username(payload.get("username"))
            if not target_user and payload.get("phone"):
                target_user = await self.telegram.find_user_by_phone(payload.get("phone"))
            if not target_user:
                return False, "user_not_found"
            return await self.telegram.send_message_to_user(target_user, payload.get("message", ""))

        return False, "unknown_source"

    async def run(self) -> None:
        await self.initialize()
        logger.info("▶️ Outbox worker запущен")

        while not self.stop_event.is_set():
            try:
                async with SessionLocal() as session:
                    outbox = await acquire_next_outbox(session)
                    if not outbox:
                        await asyncio.sleep(settings.OUTBOX_POLL_INTERVAL)
                        continue

                    logger.info(
                        "📤 Отправка из outbox: id=%s source=%s attempts=%s",
                        outbox.id,
                        outbox.payload.get("source"),
                        outbox.attempts
                    )

                    success, message = await self.process_payload(session, outbox.payload)
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
