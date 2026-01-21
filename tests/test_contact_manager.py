"""
Unit tests for Contact Manager and Circuit Breaker.

Tests the multi-layer protection system for safe Telegram contact additions:
- Circuit Breaker behavior (open/close/half-open transitions)
- Burst limit detection
- Rate limiting (inbound vs outbound)
- Database logging
- Error handling
"""

import unittest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.contact_manager import ContactAddCircuitBreaker, ContactManager
from src.database import Base, ContactAddLog


class TestContactAddCircuitBreaker(unittest.IsolatedAsyncioTestCase):
    """Unit tests for CircuitBreaker class."""

    def setUp(self):
        """Create a fresh CircuitBreaker for each test."""
        self.circuit_breaker = ContactAddCircuitBreaker()

    async def test_initial_state_is_closed(self):
        """Circuit breaker should start in CLOSED state."""
        self.assertEqual(self.circuit_breaker._state, "CLOSED")
        self.assertEqual(self.circuit_breaker._failure_count, 0)
        self.assertFalse(await self.circuit_breaker.is_open())

    async def test_is_open_returns_true_when_open(self):
        """is_open() should return True when state is OPEN."""
        self.circuit_breaker._state = "OPEN"
        self.circuit_breaker._cooldown_until = datetime.utcnow() + timedelta(seconds=300)
        self.assertTrue(await self.circuit_breaker.is_open())

    async def test_is_open_returns_false_when_closed(self):
        """is_open() should return False when state is CLOSED."""
        self.assertEqual(self.circuit_breaker._state, "CLOSED")
        self.assertFalse(await self.circuit_breaker.is_open())

    async def test_opens_after_max_failures(self):
        """Circuit breaker should open after MAX_FAILURES consecutive failures."""
        # Record 3 failures (MAX_FAILURES)
        for i in range(self.circuit_breaker.MAX_FAILURES):
            await self.circuit_breaker.record_failure(f"error_{i}")

        # Should now be OPEN
        self.assertEqual(self.circuit_breaker._state, "OPEN")
        self.assertTrue(await self.circuit_breaker.is_open())
        self.assertIsNotNone(self.circuit_breaker._cooldown_until)

    async def test_record_success_resets_failure_count(self):
        """record_success() should reset failure count to 0."""
        # Record some failures
        await self.circuit_breaker.record_failure("error_1")
        await self.circuit_breaker.record_failure("error_2")
        self.assertEqual(self.circuit_breaker._failure_count, 2)

        # Record success
        await self.circuit_breaker.record_success()

        # Failure count should be reset
        self.assertEqual(self.circuit_breaker._failure_count, 0)
        self.assertEqual(self.circuit_breaker._state, "CLOSED")

    async def test_burst_limit_detection(self):
        """check_burst_limit() should detect too many attempts in 60 seconds."""
        # Add MAX_BURST attempts
        for i in range(self.circuit_breaker.MAX_BURST):
            await self.circuit_breaker.record_add_attempt()

        # Next attempt should trigger burst limit
        can_proceed, reason = await self.circuit_breaker.check_burst_limit()

        self.assertFalse(can_proceed)
        self.assertEqual(reason, "burst_limit_exceeded")
        self.assertEqual(self.circuit_breaker._state, "OPEN")

    async def test_burst_limit_clears_old_entries(self):
        """Burst limit should only count recent attempts (last 60 seconds)."""
        # Add old attempts (> 60 seconds ago)
        old_time = datetime.utcnow() - timedelta(seconds=70)
        self.circuit_breaker._recent_adds = [old_time] * 10

        # Check burst limit - should pass because old entries are cleared
        can_proceed, reason = await self.circuit_breaker.check_burst_limit()

        self.assertTrue(can_proceed)
        self.assertEqual(reason, "ok")
        # Old entries should be removed
        self.assertEqual(len(self.circuit_breaker._recent_adds), 0)

    async def test_cooldown_expires(self):
        """Circuit breaker should transition to HALF_OPEN after cooldown."""
        # Open circuit with very short cooldown (simulate expiry)
        self.circuit_breaker._state = "OPEN"
        self.circuit_breaker._cooldown_until = datetime.utcnow() - timedelta(seconds=1)

        # Check if open - should transition to HALF_OPEN
        is_open = await self.circuit_breaker.is_open()

        self.assertFalse(is_open)
        self.assertEqual(self.circuit_breaker._state, "HALF_OPEN")
        self.assertEqual(self.circuit_breaker._failure_count, 0)

    async def test_half_open_to_closed_on_success(self):
        """Circuit breaker should transition from HALF_OPEN to CLOSED on success."""
        self.circuit_breaker._state = "HALF_OPEN"

        await self.circuit_breaker.record_success()

        self.assertEqual(self.circuit_breaker._state, "CLOSED")


class TestContactManager(unittest.IsolatedAsyncioTestCase):
    """Unit tests for ContactManager class."""

    async def asyncSetUp(self):
        """Set up test database and ContactManager."""
        # Create in-memory SQLite database for testing
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.SessionLocal = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession
        )

        # Patch the SessionLocal in contact_manager module
        self.patcher = patch('src.contact_manager.SessionLocal', self.SessionLocal)
        self.patcher.start()

        self.contact_manager = ContactManager()

    async def asyncTearDown(self):
        """Clean up test database."""
        self.patcher.stop()
        await self.engine.dispose()

    async def test_can_add_contact_initially_ok(self):
        """can_add_contact() should return True for first attempt."""
        can_add, reason = await self.contact_manager.can_add_contact(
            direction='inbound',
            telegram_user_id=12345
        )

        self.assertTrue(can_add)
        self.assertEqual(reason, "ok")

    async def test_circuit_breaker_blocks_when_open(self):
        """can_add_contact() should return False when circuit breaker is open."""
        # Open circuit breaker
        self.contact_manager.circuit_breaker._state = "OPEN"
        self.contact_manager.circuit_breaker._cooldown_until = datetime.utcnow() + timedelta(seconds=300)

        can_add, reason = await self.contact_manager.can_add_contact(
            direction='inbound',
            telegram_user_id=12345
        )

        self.assertFalse(can_add)
        self.assertEqual(reason, "circuit_breaker_open")

    async def test_already_added_returns_true(self):
        """can_add_contact() should return True with 'already_in_contacts' if user was added."""
        # Add a successful log entry
        async with self.SessionLocal() as db:
            log_entry = ContactAddLog(
                telegram_user_id=12345,
                direction='inbound',
                source='test',
                success=True
            )
            db.add(log_entry)
            await db.commit()

        can_add, reason = await self.contact_manager.can_add_contact(
            direction='inbound',
            telegram_user_id=12345
        )

        self.assertTrue(can_add)
        self.assertEqual(reason, "already_in_contacts")

    async def test_hourly_limit_inbound(self):
        """can_add_contact() should enforce hourly limit for inbound."""
        # Add exactly MAX_PER_HOUR successful entries
        async with self.SessionLocal() as db:
            for i in range(self.contact_manager.INBOUND_MAX_PER_HOUR):
                log_entry = ContactAddLog(
                    telegram_user_id=10000 + i,  # Different user IDs
                    direction='inbound',
                    source='test',
                    success=True,
                    created_at=datetime.utcnow()
                )
                db.add(log_entry)
            await db.commit()

        # Next attempt should fail
        can_add, reason = await self.contact_manager.can_add_contact(
            direction='inbound',
            telegram_user_id=99999  # New user
        )

        self.assertFalse(can_add)
        self.assertEqual(reason, "hourly_limit_inbound")

    async def test_daily_limit_inbound(self):
        """can_add_contact() should enforce daily limit for inbound."""
        # Add exactly MAX_PER_DAY successful entries
        async with self.SessionLocal() as db:
            for i in range(self.contact_manager.INBOUND_MAX_PER_DAY):
                log_entry = ContactAddLog(
                    telegram_user_id=10000 + i,
                    direction='inbound',
                    source='test',
                    success=True,
                    created_at=datetime.utcnow() - timedelta(hours=12)  # 12 hours ago
                )
                db.add(log_entry)
            await db.commit()

        # Next attempt should fail
        can_add, reason = await self.contact_manager.can_add_contact(
            direction='inbound',
            telegram_user_id=99999
        )

        self.assertFalse(can_add)
        self.assertEqual(reason, "daily_limit_inbound")

    async def test_outbound_limits_stricter(self):
        """Outbound limits should be stricter than inbound."""
        self.assertLess(
            self.contact_manager.OUTBOUND_MAX_PER_HOUR,
            self.contact_manager.INBOUND_MAX_PER_HOUR
        )
        self.assertLess(
            self.contact_manager.OUTBOUND_MAX_PER_DAY,
            self.contact_manager.INBOUND_MAX_PER_DAY
        )

    async def test_separate_limits_per_direction(self):
        """Inbound and outbound should have separate limit counters."""
        # Fill inbound limit
        async with self.SessionLocal() as db:
            for i in range(self.contact_manager.INBOUND_MAX_PER_HOUR):
                log_entry = ContactAddLog(
                    telegram_user_id=10000 + i,
                    direction='inbound',
                    source='test',
                    success=True
                )
                db.add(log_entry)
            await db.commit()

        # Outbound should still be available
        can_add, reason = await self.contact_manager.can_add_contact(
            direction='outbound',
            telegram_user_id=99999
        )

        self.assertTrue(can_add)
        self.assertEqual(reason, "ok")


class TestContactManagerDBErrors(unittest.IsolatedAsyncioTestCase):
    """Tests for DB error handling in Contact Manager (#156, #160)."""

    def setUp(self):
        """Create ContactManager for each test."""
        self.contact_manager = ContactManager(account_id=1)

    async def test_rate_limit_check_db_error_denies_operation(self):
        """Test #160: DB error during rate limit check denies operation."""
        # Mock SessionLocal to raise error
        with patch('src.contact_manager.SessionLocal') as mock_session_local:
            mock_session_local.side_effect = Exception("Database unavailable")

            # Call _check_rate_limits - should deny due to DB error
            can_add, reason = await self.contact_manager._check_rate_limits(
                telegram_user_id=12345,
                direction='inbound'
            )

            # Verify operation was denied
            self.assertFalse(can_add)
            self.assertEqual(reason, "database_error")

    async def test_logging_db_error_does_not_block(self):
        """Test #156: DB error during logging doesn't block operation."""
        from src.contact_manager import ContactAddAttempt

        # Mock SessionLocal to raise error during logging
        with patch('src.contact_manager.SessionLocal') as mock_session_local:
            mock_session_local.side_effect = Exception("Database error")

            # Create attempt
            attempt = ContactAddAttempt(
                telegram_user_id=12345,
                direction='inbound',
                source='test',
                success=True
            )

            # Call _log_attempt - should NOT raise, just log error
            try:
                await self.contact_manager._log_attempt(attempt)
                # If we get here, graceful degradation worked
                success = True
            except Exception:
                success = False

            self.assertTrue(success, "Logging failure should not block operation")


if __name__ == '__main__':
    unittest.main()
