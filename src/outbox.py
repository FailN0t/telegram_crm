"""
Outbox utilities for transactional message delivery.
"""

import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select

from src.config import settings
from src.database import MessageOutbox, MessageDeliveryAttempt


_sqlite_outbox_lock = asyncio.Lock()


def build_idempotency_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def enqueue_outbox(
    db: AsyncSession,
    idempotency_key: str,
    account_id: int,
    operator_id: Optional[int],
    chat_id: int,
    payload: dict
) -> Tuple[MessageOutbox, bool]:
    result = await db.execute(
        select(MessageOutbox).filter_by(idempotency_key=idempotency_key)
    )
    existing = result.scalars().first()
    if existing:
        return existing, False

    outbox = MessageOutbox(
        idempotency_key=idempotency_key,
        account_id=account_id,
        operator_id=operator_id,
        chat_id=chat_id,
        payload=payload,
        status="queued",
        attempts=0
    )
    db.add(outbox)
    await db.commit()
    await db.refresh(outbox)
    return outbox, True


def mark_attempt(
    db: AsyncSession,
    outbox: MessageOutbox,
    status: str,
    error_message: Optional[str] = None
) -> None:
    attempt = MessageDeliveryAttempt(
        outbox_id=outbox.id,
        attempt=outbox.attempts,
        status=status,
        error_message=error_message or ""
    )
    db.add(attempt)


def schedule_retry(attempts: int) -> datetime:
    delay = settings.OUTBOX_RETRY_BASE_SECONDS * (2 ** max(attempts - 1, 0))
    return datetime.utcnow() + timedelta(seconds=delay)


def update_outbox_status(
    db: AsyncSession,
    outbox: MessageOutbox,
    status: str,
    next_attempt_at: Optional[datetime] = None
) -> None:
    outbox.status = status
    outbox.updated_at = datetime.utcnow()
    outbox.next_attempt_at = next_attempt_at
    db.add(outbox)


async def _acquire_next_outbox(db: AsyncSession, dialect_name: Optional[str]) -> Optional[MessageOutbox]:
    now = datetime.utcnow()
    processing_chat_ids = select(MessageOutbox.chat_id).filter(
        MessageOutbox.status == "processing",
        MessageOutbox.chat_id > 0
    )
    stmt = select(MessageOutbox).filter(
        MessageOutbox.status.in_(["queued", "failed"]),
        or_(
            MessageOutbox.chat_id == 0,
            ~MessageOutbox.chat_id.in_(processing_chat_ids)
        ),
        or_(
            MessageOutbox.next_attempt_at.is_(None),
            MessageOutbox.next_attempt_at <= now
        )
    ).order_by(MessageOutbox.created_at.asc()).limit(1)

    if dialect_name and dialect_name != "sqlite":
        stmt = stmt.with_for_update(skip_locked=True)

    result = await db.execute(stmt)
    outbox = result.scalars().first()
    if not outbox:
        return None

    outbox.status = "processing"
    outbox.updated_at = datetime.utcnow()
    db.add(outbox)
    await db.commit()
    await db.refresh(outbox)
    return outbox


async def acquire_next_outbox(db: AsyncSession) -> Optional[MessageOutbox]:
    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind else None
    if dialect_name == "sqlite":
        async with _sqlite_outbox_lock:
            return await _acquire_next_outbox(db, dialect_name)
    return await _acquire_next_outbox(db, dialect_name)


async def mark_outbox_result(
    db: AsyncSession,
    outbox: MessageOutbox,
    success: bool,
    error_message: Optional[str] = None
) -> None:
    outbox.attempts += 1
    if success:
        update_outbox_status(db, outbox, "sent")
        mark_attempt(db, outbox, "sent", error_message="")
    else:
        if outbox.attempts >= settings.OUTBOX_MAX_ATTEMPTS:
            update_outbox_status(db, outbox, "dead")
        else:
            next_attempt = schedule_retry(outbox.attempts)
            update_outbox_status(db, outbox, "failed", next_attempt_at=next_attempt)
        mark_attempt(db, outbox, "failed", error_message=error_message)

    await db.commit()


async def mark_outbox_non_retryable(
    db: AsyncSession,
    outbox: MessageOutbox,
    error_message: str
) -> None:
    outbox.attempts += 1
    update_outbox_status(db, outbox, "dead")
    mark_attempt(db, outbox, "dead", error_message=error_message)
    await db.commit()
