"""
Outbox utilities for transactional message delivery.
"""

import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, and_, select
from sqlalchemy.exc import IntegrityError

from src.config import settings
from src.database import MessageOutbox, MessageDeliveryAttempt
from src.logger import logger


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
    """
    Enqueue message to outbox with atomic idempotency check.

    Uses INSERT + catch IntegrityError pattern for atomic idempotency.
    This is faster and more reliable than SELECT + INSERT under high concurrency.

    Args:
        db: Database session
        idempotency_key: Unique key for deduplication
        account_id: Telegram account ID
        operator_id: Optional operator ID
        chat_id: Target chat ID
        payload: Message payload

    Returns:
        (MessageOutbox, is_new) tuple where is_new indicates if this was a new insert
    """
    # Optimistic INSERT - assume key doesn't exist (common case)
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

    try:
        # Try to commit - will fail if idempotency_key already exists
        await db.commit()
        await db.refresh(outbox)
        return outbox, True  # New message queued

    except IntegrityError as e:
        # Duplicate idempotency_key - rollback and fetch existing
        await db.rollback()

        # Fetch existing message
        result = await db.execute(
            select(MessageOutbox).filter_by(idempotency_key=idempotency_key)
        )
        existing = result.scalars().first()

        if existing:
            logger.debug(f"ℹ️ Duplicate idempotency_key: {idempotency_key}, returning existing message")
            return existing, False  # Existing message found

        # Edge case: IntegrityError for different reason (shouldn't happen)
        logger.error(f"❌ IntegrityError but no existing message found: {e}")
        raise


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
    # Timeout для orphaned messages: если message в "processing" > 5 минут, считаем его orphaned
    timeout_threshold = now - timedelta(minutes=5)

    # Исключаем только АКТИВНЫЕ processing messages (не orphaned)
    processing_chat_ids = select(MessageOutbox.chat_id).filter(
        MessageOutbox.status == "processing",
        MessageOutbox.updated_at >= timeout_threshold,  # только fresh processing
        MessageOutbox.chat_id > 0
    )

    stmt = select(MessageOutbox).filter(
        or_(
            # Обычные queued/failed messages
            MessageOutbox.status.in_(["queued", "failed"]),
            # НОВОЕ: orphaned processing messages (старше 5 минут)
            and_(
                MessageOutbox.status == "processing",
                MessageOutbox.updated_at < timeout_threshold
            )
        ),
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
    """
    Mark outbox message result and commit.

    Fix #112: Wrap commit in try/except for proper error handling.
    """
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

    # Fix #112: Wrap commit in try/except
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка commit в mark_outbox_result для outbox_id={outbox.id}: {e}")
        raise


async def mark_outbox_non_retryable(
    db: AsyncSession,
    outbox: MessageOutbox,
    error_message: str
) -> None:
    """
    Mark outbox message as non-retryable (dead) and commit.

    Fix #112: Wrap commit in try/except for proper error handling.
    """
    outbox.attempts += 1
    update_outbox_status(db, outbox, "dead")
    mark_attempt(db, outbox, "dead", error_message=error_message)

    # Fix #112: Wrap commit in try/except
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка commit в mark_outbox_non_retryable для outbox_id={outbox.id}: {e}")
        raise
