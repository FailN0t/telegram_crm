"""
Data retention cleanup utilities.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional

from sqlalchemy import delete

from src.config import settings
from src.database import SessionLocal, UiMessageHistory, UiEventLog, AuditLog, MessageInbox
from src.logger import logger


def _cutoff(days: int, now: datetime) -> Optional[datetime]:
    if days is None or days <= 0:
        return None
    return now - timedelta(days=days)


async def run_retention(now: Optional[datetime] = None) -> Dict[str, dict]:
    """Delete rows older than retention windows."""
    now = now or datetime.utcnow()
    results: Dict[str, dict] = {}

    async with SessionLocal() as session:
        try:  # Added try-except with rollback (#126)
            tasks = [
                ("ui_message_history", UiMessageHistory, settings.UI_MESSAGE_RETENTION_DAYS),
                ("ui_event_log", UiEventLog, settings.UI_EVENT_RETENTION_DAYS),
                ("audit_log", AuditLog, settings.AUDIT_LOG_RETENTION_DAYS),
                ("message_inbox", MessageInbox, settings.MESSAGE_INBOX_RETENTION_DAYS),
            ]

            for name, model, days in tasks:
                cutoff = _cutoff(days, now)
                if not cutoff:
                    continue
                result = await session.execute(
                    delete(model).where(model.created_at < cutoff)
                )
                deleted = result.rowcount or 0
                results[name] = {
                    "deleted": deleted,
                    "cutoff": cutoff.isoformat() + "Z"
                }

            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error(f"❌ Retention cleanup failed: {exc}")
            raise

    logger.info("✅ Data retention cleanup finished: %s", results)
    return results


if __name__ == "__main__":
    asyncio.run(run_retention())
