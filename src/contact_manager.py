"""
Contact Manager for safe Telegram contact additions.

This module provides multi-layer protection against Telegram account bans when
adding users to contacts for phone number extraction:

1. Circuit Breaker - automatic shutoff after failures
2. Burst Limit - prevents infinite loops (5 adds/minute max)
3. Rate Limits - separate limits for inbound (50/hour, 150/day) and outbound (3/hour, 10/day)
4. Timeout Protection - 10s max per operation
5. Concurrency Lock - prevents race conditions
6. Flood Detection - auto-detects Telegram flood errors
7. Audit Logging - all attempts logged to database
8. Health Monitoring - failure rate tracking

Usage:
    from src.contact_manager import contact_manager

    success, phone = await contact_manager.add_to_contacts_with_protection(
        client=telegram_client,
        telegram_user_id=12345,
        first_name="John",
        last_name="Doe",
        username="johndoe",
        direction='inbound',  # or 'outbound'
        source='incoming_message'
    )
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, TYPE_CHECKING
import asyncio
from collections import defaultdict
from sqlalchemy import select, and_, func

from src.logger import logger
from src.database import SessionLocal, ContactAddLog

if TYPE_CHECKING:
    from telethon import TelegramClient


@dataclass
class ContactAddAttempt:
    """
    Data class for contact addition attempt information.

    Eliminates data clumps by grouping related parameters.
    """
    telegram_user_id: int
    direction: str
    source: str
    success: bool


class PerUserLockManager:
    """
    Manages per-user locks for high concurrency scenarios.

    Instead of one global lock blocking ALL operations, we create a lock per user_id.
    This allows parallel processing of different users while preventing race conditions
    for the same user.

    Features:
        - Automatic lock creation on demand
        - Automatic cleanup of unused locks (TTL-based)
        - O(1) lock acquisition
        - Thread-safe for async context

    Example:
        lock_mgr = PerUserLockManager()
        user_lock = await lock_mgr.get_lock(12345)
        async with user_lock:
            # Critical section for user 12345
            pass
        # Other users can run in parallel
    """

    def __init__(self, lock_ttl_seconds: int = 300):
        """
        Initialize lock manager.

        Args:
            lock_ttl_seconds: Time-to-live for unused locks (default: 5 minutes)
        """
        self._locks: Dict[int, asyncio.Lock] = {}
        self._lock_last_used: Dict[int, datetime] = {}
        self._manager_lock = asyncio.Lock()  # Protects _locks dict modifications
        self._lock_ttl = timedelta(seconds=lock_ttl_seconds)
        self._cleanup_task: Optional[asyncio.Task] = None

    async def get_lock(self, user_id: int) -> asyncio.Lock:
        """
        Get or create lock for specific user.

        Thread-safe: Uses internal lock to protect dict modifications.

        Args:
            user_id: Telegram user ID

        Returns:
            asyncio.Lock for this user
        """
        async with self._manager_lock:
            if user_id not in self._locks:
                self._locks[user_id] = asyncio.Lock()
                logger.debug(f"🔒 Created new lock for user {user_id}")

            self._lock_last_used[user_id] = datetime.utcnow()
            return self._locks[user_id]

    async def cleanup_stale_locks(self):
        """
        Remove locks that haven't been used for TTL period.

        This prevents memory leak from accumulating locks for users who
        only interact once.
        """
        async with self._manager_lock:
            now = datetime.utcnow()
            stale_users = [
                user_id for user_id, last_used in self._lock_last_used.items()
                if now - last_used > self._lock_ttl
            ]

            for user_id in stale_users:
                # Only remove if lock is not currently held
                lock = self._locks.get(user_id)
                if lock and not lock.locked():
                    del self._locks[user_id]
                    del self._lock_last_used[user_id]
                    logger.debug(f"🗑️ Cleaned up stale lock for user {user_id}")

    async def start_cleanup_task(self):
        """Start background task for periodic cleanup."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        """Background loop for cleaning up stale locks."""
        while True:
            try:
                await asyncio.sleep(60)  # Cleanup every minute
                await self.cleanup_stale_locks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error in lock cleanup loop: {e}")

    async def stop_cleanup_task(self):
        """Stop background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    def get_stats(self) -> dict:
        """Get statistics about lock usage."""
        return {
            "total_locks": len(self._locks),
            "active_locks": sum(1 for lock in self._locks.values() if lock.locked()),
        }


class ContactAddCircuitBreaker:
    """
    Circuit Breaker for protection against programming failures.

    Implements the Circuit Breaker pattern to automatically disable contact
    additions when errors occur too frequently, preventing Telegram account bans.

    States:
        CLOSED: Normal operation, allows contact additions
        OPEN: Protection active, blocks all operations for cooldown period
        HALF_OPEN: Testing recovery after cooldown

    Automatic shutoff triggers:
        - 3 consecutive failures
        - 5+ additions within 60 seconds (burst detection)
        - Telegram flood error detected

    Attributes:
        MAX_FAILURES: Maximum consecutive failures before opening (3)
        COOLDOWN_SECONDS: Cooldown period in seconds (300 = 5 minutes)
        MAX_BURST: Maximum additions per 60 seconds (5)

    Thread Safety:
        All public methods are protected by asyncio.Lock to prevent race conditions
        in concurrent async environment.
    """

    def __init__(self):
        self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._failure_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._cooldown_until: Optional[datetime] = None

        # CRITICAL limits - HARD-CODED (not from env!)
        self.MAX_FAILURES = 3  # After 3 errors in a row - shut off
        self.COOLDOWN_SECONDS = 300  # 5 minutes no contact additions
        self.MAX_BURST = 5  # No more than 5 additions per 60 seconds

        self._recent_adds: List[datetime] = []  # Timestamps of recent additions

        # Async lock - protects all state modifications in async context
        self._lock = asyncio.Lock()

    async def is_open(self) -> bool:
        """
        Check if circuit breaker is open (protection active).

        Async and thread-safe: Uses asyncio.Lock to prevent race conditions.

        Returns:
            True if circuit is open and operations should be blocked
        """
        async with self._lock:
            if self._state == "OPEN":
                # Check if cooldown period expired
                if self._cooldown_until and datetime.utcnow() >= self._cooldown_until:
                    logger.info("🔄 Circuit breaker: transition to HALF_OPEN")
                    self._state = "HALF_OPEN"
                    self._failure_count = 0
                    return False
                return True
            return False

    async def check_burst_limit(self) -> Tuple[bool, str]:
        """
        Check burst limit - protection against infinite loops.

        If >= MAX_BURST attempts in last 60 seconds, circuit opens immediately.
        This prevents buggy while loops from causing Telegram bans.

        Async and thread-safe: Uses asyncio.Lock to prevent race conditions.

        Returns:
            (can_proceed, reason) tuple
        """
        async with self._lock:
            now = datetime.utcnow()
            minute_ago = now - timedelta(seconds=60)

            # Remove old entries
            self._recent_adds = [ts for ts in self._recent_adds if ts > minute_ago]

            if len(self._recent_adds) >= self.MAX_BURST:
                logger.error(
                    f"🚨 CIRCUIT BREAKER: Burst limit exceeded! "
                    f"{len(self._recent_adds)} adds in 60 seconds. "
                    f"Possible infinite loop detected!"
                )
                self._open_circuit_unsafe("burst_limit_exceeded")
                return False, "burst_limit_exceeded"

            return True, "ok"

    async def record_add_attempt(self):
        """
        Record an addition attempt (for burst detection).

        Async and thread-safe: Uses asyncio.Lock and also cleans old entries.
        """
        async with self._lock:
            now = datetime.utcnow()
            # Cleanup old entries (prevents memory leak)
            minute_ago = now - timedelta(seconds=60)
            self._recent_adds = [ts for ts in self._recent_adds if ts > minute_ago]
            # Add new entry
            self._recent_adds.append(now)

    async def record_success(self):
        """
        Record successful addition - resets failure counter.

        Async and thread-safe: Uses asyncio.Lock.
        """
        async with self._lock:
            if self._state == "HALF_OPEN":
                logger.info("✅ Circuit breaker: transition back to CLOSED")

            self._failure_count = 0
            self._state = "CLOSED"

    async def record_failure(self, reason: str):
        """
        Record a failure.

        After MAX_FAILURES consecutive failures, circuit breaker opens.

        Async and thread-safe: Uses asyncio.Lock.

        Args:
            reason: Reason for failure (for logging)
        """
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.utcnow()

            logger.warning(
                f"⚠️ Contact add failure #{self._failure_count}: {reason}"
            )

            if self._failure_count >= self.MAX_FAILURES:
                self._open_circuit_unsafe(reason)

    def _open_circuit_unsafe(self, reason: str):
        """
        Open circuit breaker - stop all contact additions.

        UNSAFE: Must be called with lock held!

        Args:
            reason: Reason for opening (logged and used for alerting)
        """
        self._state = "OPEN"
        self._cooldown_until = datetime.utcnow() + timedelta(
            seconds=self.COOLDOWN_SECONDS
        )

        logger.error(
            f"🚨 CIRCUIT BREAKER OPENED: Stopping contact additions for "
            f"{self.COOLDOWN_SECONDS}s. Reason: {reason}"
        )

        # TODO: Send admin alert!
        # await send_admin_alert(
        #     f"Circuit breaker opened: {reason}. "
        #     f"Contact additions stopped until {self._cooldown_until}"
        # )

    async def _open_circuit(self, reason: str):
        """
        Open circuit breaker - stop all contact additions.

        Async and thread-safe wrapper for _open_circuit_unsafe.

        Args:
            reason: Reason for opening (logged and used for alerting)
        """
        async with self._lock:
            self._open_circuit_unsafe(reason)


class ContactManager:
    """
    Manager for safe Telegram contact additions with multi-layer protection.

    This class enforces rate limits, prevents Telegram account bans, and provides
    audit logging for all contact addition attempts.

    Rate Limits:
        Inbound (customer writes first):
            - 50 per hour
            - 150 per day

        Outbound (we write first):
            - 3 per hour
            - 10 per day

    Protection Layers:
        1. Circuit Breaker check
        2. Burst limit check (5/minute)
        3. Rate limit check (direction-specific)
        4. Already-added check
        5. Telegram API call with timeout
        6. Error handling (flood/privacy/timeout)
        7. Database logging
        8. Circuit breaker update

    Usage:
        contact_manager = ContactManager()
        success, phone = await contact_manager.add_to_contacts_with_protection(...)

    Attributes:
        INBOUND_MAX_PER_HOUR: Hourly limit for inbound (50)
        INBOUND_MAX_PER_DAY: Daily limit for inbound (150)
        OUTBOUND_MAX_PER_HOUR: Hourly limit for outbound (3)
        OUTBOUND_MAX_PER_DAY: Daily limit for outbound (10)
    """

    # Rate limits for INBOUND (inbound) - conservative
    INBOUND_MAX_PER_HOUR = 50
    INBOUND_MAX_PER_DAY = 150  # Telegram allows 200, but we're conservative

    # Rate limits for OUTBOUND (outbound) - VERY strict
    OUTBOUND_MAX_PER_HOUR = 3
    OUTBOUND_MAX_PER_DAY = 10

    def __init__(self):
        self.circuit_breaker = ContactAddCircuitBreaker()
        self._lock_manager = PerUserLockManager(lock_ttl_seconds=300)  # Per-user locks with 5min TTL
        self._initialized = False

    async def initialize(self):
        """
        Initialize Contact Manager - start background tasks.

        Fix #178: Starts cleanup task for per-user locks to prevent memory leak.

        This should be called once at application startup.
        """
        if not self._initialized:
            await self._lock_manager.start_cleanup_task()
            self._initialized = True
            logger.info("✅ Contact Manager initialized: cleanup task started")

    async def _log_attempt(self, attempt: ContactAddAttempt) -> None:
        """
        Log contact addition attempt to database.

        Helper method to eliminate code duplication (DRY principle).
        Gracefully handles DB errors without interrupting the main operation.

        Args:
            attempt: ContactAddAttempt dataclass with all necessary information
        """
        try:
            async with SessionLocal() as db:
                log_entry = ContactAddLog(
                    telegram_user_id=attempt.telegram_user_id,
                    direction=attempt.direction,
                    source=attempt.source,
                    success=attempt.success
                )
                db.add(log_entry)
                await db.commit()
        except Exception as e:
            logger.error(
                f"❌ Failed to log attempt to database: {e} "
                f"(user_id={attempt.telegram_user_id}, success={attempt.success})"
            )
            # Continue operation even if logging fails (graceful degradation)

    async def _get_existing_contact_phone(
        self,
        client: "TelegramClient",
        telegram_user_id: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Get phone number for already-added contact.

        This is a read-only operation that doesn't require lock.

        Args:
            client: TelegramClient instance
            telegram_user_id: Telegram user ID

        Returns:
            (success, phone_number) tuple
        """
        try:
            sender = await asyncio.wait_for(
                client.get_entity(telegram_user_id),
                timeout=5.0
            )
            phone_number = getattr(sender, 'phone', None)
            logger.info(
                f"ℹ️ User already in contacts, phone: {phone_number or 'hidden'}"
            )
            return True, phone_number
        except asyncio.TimeoutError:
            logger.error("❌ Timeout getting entity for existing contact")
            return False, None
        except Exception as e:
            logger.error(f"❌ Error getting entity: {e}")
            return False, None

    async def _do_telegram_api_call(
        self,
        client: "TelegramClient",
        telegram_user_id: int,
        first_name: str,
        last_name: Optional[str],
        username: Optional[str],
        direction: str,
        source: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Execute Telegram API call to add contact with comprehensive error handling.

        Handles:
        - Timeout errors (10s timeout)
        - Flood errors (opens circuit breaker immediately)
        - Privacy errors (logged but not counted as failure)
        - Other errors (logged and counted as failure)

        Args:
            client: TelegramClient instance
            telegram_user_id: Telegram user ID
            first_name: User first name
            last_name: User last name (optional)
            username: Telegram username (optional)
            direction: 'inbound' or 'outbound'
            source: Source of request

        Returns:
            (success, phone_number) tuple
        """
        try:
            # Check client connected again (right before API call to minimize TOCTOU)
            if not client.is_connected():
                logger.error("❌ Telegram client disconnected before API call")
                await self.circuit_breaker.record_failure("client_disconnected")
                return False, None

            logger.info(
                f"📇 [{direction}] Adding contact: "
                f"{first_name} {last_name or ''} (@{username})"
            )

            from telethon import functions

            # TIMEOUT on operation - 10 seconds max
            result = await asyncio.wait_for(
                client(functions.contacts.AddContactRequest(
                    id=username or telegram_user_id,
                    first_name=first_name,
                    last_name=last_name or "",
                    phone="",
                    add_phone_privacy_exception=False
                )),
                timeout=10.0
            )

            # Wait for Telegram to update
            await asyncio.sleep(1)

            # Get updated user data
            sender = await asyncio.wait_for(
                client.get_entity(telegram_user_id),
                timeout=5.0
            )
            phone_number = getattr(sender, 'phone', None)

            # SUCCESS - log to database
            await self._log_attempt(ContactAddAttempt(
                telegram_user_id=telegram_user_id,
                direction=direction,
                source=source,
                success=True
            ))

            # Reset circuit breaker (successful operation)
            await self.circuit_breaker.record_success()

            if phone_number:
                logger.info(f"✅ Contact added successfully, phone: {phone_number}")
            else:
                logger.info(f"✅ Contact added, but phone hidden by privacy settings")

            return True, phone_number

        except asyncio.TimeoutError:
            logger.error(
                f"❌ Timeout adding contact "
                f"(user_id={telegram_user_id}, direction={direction})"
            )
            await self.circuit_breaker.record_failure("timeout")

            # Log failure to database
            await self._log_attempt(ContactAddAttempt(
                telegram_user_id=telegram_user_id,
                direction=direction,
                source=source,
                success=False
            ))

            return False, None

        except Exception as e:
            error_str = str(e).lower()

            # Special handling for Telegram flood errors
            if "flood" in error_str or "too many" in error_str:
                logger.error(
                    f"🚨 TELEGRAM FLOOD LIMIT HIT: {e}. "
                    f"Immediately opening circuit breaker!"
                )
                # CRITICAL - open circuit breaker IMMEDIATELY
                await self.circuit_breaker._open_circuit("telegram_flood_limit")

            elif "user_privacy" in error_str or "privacy" in error_str:
                # Not an error - just privacy settings
                logger.info(
                    f"ℹ️ User denied contact addition "
                    f"(user_id={telegram_user_id})"
                )
                # DON'T count this as failure for circuit breaker

                # BUT log to DB for statistics and to prevent duplicate attempts
                await self._log_attempt(ContactAddAttempt(
                    telegram_user_id=telegram_user_id,
                    direction=direction,
                    source=source,
                    success=False
                ))

                return False, None

            else:
                # Other error - log and increase failure count
                logger.error(
                    f"❌ Error adding contact: {e} "
                    f"(user_id={telegram_user_id}, direction={direction})"
                )
                await self.circuit_breaker.record_failure(str(e)[:100])

            # Log failure to database
            await self._log_attempt(ContactAddAttempt(
                telegram_user_id=telegram_user_id,
                direction=direction,
                source=source,
                success=False
            ))

            return False, None

    async def _attempt_add_with_lock(
        self,
        client: "TelegramClient",
        telegram_user_id: int,
        first_name: str,
        last_name: Optional[str],
        username: Optional[str],
        direction: str,
        source: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Attempt to add contact with per-user lock protection.

        CRITICAL SECTION MINIMIZATION:
        Lock is held ONLY for in-memory checks (< 1ms), NOT during Telegram API call.
        This allows parallel processing of different users.

        Lock scope:
        1. Double-check circuit breaker (fast in-memory)
        2. Double-check burst limit (fast in-memory)
        3. Record attempt timestamp (fast in-memory)

        NO LOCK during:
        - Telegram API call (can take 1-5 seconds)
        - Database logging (async, non-blocking for other users)

        Args:
            client: TelegramClient instance
            telegram_user_id: Telegram user ID
            first_name: User first name
            last_name: User last name (optional)
            username: Telegram username (optional)
            direction: 'inbound' or 'outbound'
            source: Source of request

        Returns:
            (success, phone_number) tuple
        """
        # Get per-user lock (O(1) lookup, creates if not exists)
        user_lock = await self._lock_manager.get_lock(telegram_user_id)

        # CRITICAL SECTION START - minimize time under lock!
        async with user_lock:
            # Double-check ONLY fast in-memory conditions
            # Circuit breaker might have opened while we waited for lock
            if await self.circuit_breaker.is_open():
                logger.info(
                    f"ℹ️ Circuit breaker opened while waiting for lock "
                    f"(user_id={telegram_user_id})"
                )
                return False, None

            # Burst limit might have been exceeded while we waited
            can_burst, burst_reason = await self.circuit_breaker.check_burst_limit()
            if not can_burst:
                logger.info(
                    f"ℹ️ Burst limit exceeded after lock acquired: {burst_reason} "
                    f"(user_id={telegram_user_id})"
                )
                return False, None

            # Record attempt (for burst detection) - fast in-memory operation
            await self.circuit_breaker.record_add_attempt()

        # CRITICAL SECTION END - lock released!
        # Other users can now acquire their locks in parallel

        # Execute Telegram API call WITHOUT lock - can take 1-5 seconds
        # This allows parallel processing of different users
        return await self._do_telegram_api_call(
            client, telegram_user_id, first_name, last_name,
            username, direction, source
        )

    async def can_add_contact(
        self,
        direction: str,
        telegram_user_id: int
    ) -> Tuple[bool, str]:
        """
        Check if contact can be added (with protection checks).

        Uses single DB session for all queries to prevent connection pool exhaustion.

        Args:
            direction: 'inbound' (customer writes) or 'outbound' (we write)
            telegram_user_id: Telegram user ID

        Returns:
            (can_add, reason) tuple where reason can be:
                - "ok": can add
                - "already_in_contacts": already added
                - "circuit_breaker_open": protection active
                - "burst_limit_exceeded": too fast
                - "hourly_limit_inbound" / "hourly_limit_outbound"
                - "daily_limit_inbound" / "daily_limit_outbound"
        """
        # 1. CIRCUIT BREAKER CHECK (highest priority)
        if await self.circuit_breaker.is_open():
            logger.error(
                "🚨 Circuit breaker OPEN - contact additions disabled"
            )
            return False, "circuit_breaker_open"

        # 2. BURST LIMIT CHECK (protection against infinite loops)
        can_burst, reason = await self.circuit_breaker.check_burst_limit()
        if not can_burst:
            return False, reason

        # 3-6. All DB checks in ONE session (prevents connection pool exhaustion)
        # Fix #156, #160: Graceful degradation if DB is unavailable
        try:
            async with SessionLocal() as db:
                # 3. Check if already added (with LIMIT 1 for performance)
                existing = await db.execute(
                    select(ContactAddLog)
                    .where(
                        and_(
                            ContactAddLog.telegram_user_id == telegram_user_id,
                            ContactAddLog.success == True
                        )
                    )
                    .limit(1)  # Performance: only need to know if exists
                )
                if existing.scalars().first():
                    return True, "already_in_contacts"

                # 4. Select limits based on direction
                if direction == 'inbound':
                    max_hour = self.INBOUND_MAX_PER_HOUR
                    max_day = self.INBOUND_MAX_PER_DAY
                else:  # outbound
                    max_hour = self.OUTBOUND_MAX_PER_HOUR
                    max_day = self.OUTBOUND_MAX_PER_DAY

                # 5. Check hourly limit
                hour_ago = datetime.utcnow() - timedelta(hours=1)
                hour_result = await db.execute(
                    select(func.count(ContactAddLog.id)).where(
                        and_(
                            ContactAddLog.direction == direction,
                            ContactAddLog.created_at >= hour_ago,
                            ContactAddLog.success == True
                        )
                    )
                )
                hour_count = hour_result.scalar()

                if hour_count >= max_hour:
                    logger.warning(
                        f"⚠️ Hourly limit reached for {direction}: "
                        f"{hour_count}/{max_hour}"
                    )
                    return False, f"hourly_limit_{direction}"

                # 6. Check daily limit
                day_ago = datetime.utcnow() - timedelta(days=1)
                day_result = await db.execute(
                    select(func.count(ContactAddLog.id)).where(
                        and_(
                            ContactAddLog.direction == direction,
                            ContactAddLog.created_at >= day_ago,
                            ContactAddLog.success == True
                        )
                    )
                )
                day_count = day_result.scalar()

                if day_count >= max_day:
                    logger.warning(
                        f"⚠️ Daily limit reached for {direction}: "
                        f"{day_count}/{max_day}"
                    )
                    return False, f"daily_limit_{direction}"

                return True, "ok"
        except Exception as e:
            # Fix #156, #160: DB error during limit check
            # Pessimistic approach: deny operation if we can't verify limits
            # This prevents account bans due to untracked additions
            logger.error(
                f"❌ Database error during rate limit check: {e} "
                f"(user_id={telegram_user_id}, direction={direction})"
            )
            logger.error("🚨 DENYING contact addition - cannot verify rate limits (DB unavailable)")
            return False, "database_error"

    async def add_to_contacts_with_protection(
        self,
        client: "TelegramClient",
        telegram_user_id: int,
        first_name: str,
        last_name: Optional[str],
        username: Optional[str],
        direction: str,
        source: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Add Telegram user to contacts with full protection.

        Main orchestrator method that coordinates all protection layers.
        Refactored for improved maintainability (210 lines → 40 lines).

        Protection layers:
        1. Client connection check
        2. Rate limits and circuit breaker check
        3. Already-added check
        4. Critical section with lock
        5. Telegram API call with error handling
        6. Database logging

        Args:
            client: TelegramClient instance
            telegram_user_id: Telegram user ID
            first_name: User first name
            last_name: User last name (optional)
            username: Telegram username (optional)
            direction: 'inbound' or 'outbound'
            source: Source of request ('incoming_message', 'crm_request', etc.)

        Returns:
            (success, phone_number) tuple where:
                - success: True if contact was added or already exists
                - phone_number: Phone number if available, None if hidden/failed
        """
        # 1. Pre-check: client connection (fast, no lock)
        if not client.is_connected():
            logger.error("❌ Telegram client not connected")
            return False, None

        # 2. Check all limits (DB queries, no lock)
        can_add, reason = await self.can_add_contact(direction, telegram_user_id)

        if not can_add:
            logger.info(
                f"ℹ️ Cannot add contact: {reason} "
                f"(user_id={telegram_user_id}, direction={direction})"
            )
            return False, None

        # 3. Handle already-added case (read-only, no lock)
        if reason == "already_in_contacts":
            return await self._get_existing_contact_phone(client, telegram_user_id)

        # 4. Attempt addition with lock protection
        return await self._attempt_add_with_lock(
            client, telegram_user_id, first_name, last_name,
            username, direction, source
        )


# Singleton instance
contact_manager = ContactManager()
