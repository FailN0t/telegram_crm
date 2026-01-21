"""
Tests for Contact Manager DB error handling.

Validates fixes for:
- #156: Нет обработки DB errors при logging
- #160: DB failure при logging блокирует всю операцию

These tests verify that:
1. DB errors during logging don't block the main operation (graceful degradation)
2. DB errors during rate limit checks safely deny the operation (pessimistic approach)
3. Operations continue normally when DB is available
"""

import asyncio
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Optional


class TestContactManagerDBErrors(unittest.TestCase):
    """Test DB error handling in ContactManager"""

    def setUp(self):
        """Set up test fixtures"""
        # Import here to avoid circular import
        from src.contact_manager import ContactManager

        # Create ContactManager with mock circuit breaker
        self.manager = ContactManager(account_id=1)

        # Mock circuit breaker to always allow
        self.manager.circuit_breaker.is_open = AsyncMock(return_value=False)
        self.manager.circuit_breaker.check_burst_limit = AsyncMock(return_value=(True, "ok"))
        self.manager.circuit_breaker.record_add_attempt = AsyncMock()
        self.manager.circuit_breaker.record_success = AsyncMock()
        self.manager.circuit_breaker.record_failure = AsyncMock()

    def tearDown(self):
        """Clean up after each test"""
        asyncio.run(self._cleanup())

    async def _cleanup(self):
        """Async cleanup"""
        if hasattr(self, 'manager') and hasattr(self.manager, '_lock_manager'):
            await self.manager._lock_manager.cleanup_stale_locks()

    def test_logging_failure_does_not_block_operation(self):
        """Test #156: DB error during logging doesn't block the operation"""
        async def run_test():
            # Mock SessionLocal to raise error during logging
            with patch('src.contact_manager.SessionLocal') as mock_session_local:
                # First call (during _check_rate_limits) - works normally
                # Second call (during _log_attempt) - raises error
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)

                call_count = 0

                async def session_side_effect():
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        # First call - rate limit check (works)
                        mock_db = AsyncMock()
                        mock_result = Mock()
                        mock_result.scalars.return_value.first.return_value = None
                        mock_result.scalar.return_value = 0
                        mock_db.execute = AsyncMock(return_value=mock_result)

                        session = AsyncMock()
                        session.__aenter__ = AsyncMock(return_value=mock_db)
                        session.__aexit__ = AsyncMock(return_value=None)
                        return session
                    else:
                        # Second call - logging (fails)
                        raise Exception("Database connection error")

                mock_session_local.side_effect = session_side_effect

                # Create attempt
                from src.contact_manager import ContactAddAttempt
                attempt = ContactAddAttempt(
                    telegram_user_id=12345,
                    direction='inbound',
                    source='test',
                    success=True
                )

                # Call _log_attempt - should not raise, just log error
                await self.manager._log_attempt(attempt)

                # Verify operation completed (no exception raised)
                self.assertTrue(True, "Logging failure should not block operation")

        asyncio.run(run_test())

    def test_rate_limit_check_failure_denies_operation(self):
        """Test #160: DB error during rate limit check denies the operation (pessimistic)"""
        async def run_test():
            # Mock SessionLocal to raise error during rate limit check
            with patch('src.contact_manager.SessionLocal') as mock_session_local:
                # Make SessionLocal raise error
                mock_session_local.side_effect = Exception("Database unavailable")

                # Call _check_rate_limits - should return False with database_error reason
                can_add, reason = await self.manager._check_rate_limits(
                    telegram_user_id=12345,
                    direction='inbound'
                )

                # Verify operation was denied
                self.assertFalse(can_add, "Should deny operation when DB unavailable")
                self.assertEqual(reason, "database_error")

        asyncio.run(run_test())

    def test_rate_limit_check_success_when_db_available(self):
        """Test: Rate limit check succeeds when DB is available"""
        async def run_test():
            # Mock SessionLocal to work normally
            with patch('src.contact_manager.SessionLocal') as mock_session_local:
                mock_db = AsyncMock()

                # Mock query results - no existing contact, no limits exceeded
                mock_result = Mock()
                mock_result.scalars.return_value.first.return_value = None  # No existing contact
                mock_result.scalar.return_value = 0  # 0 additions in time window
                mock_db.execute = AsyncMock(return_value=mock_result)

                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_local.return_value = mock_session

                # Call _check_rate_limits - should succeed
                can_add, reason = await self.manager._check_rate_limits(
                    telegram_user_id=12345,
                    direction='inbound'
                )

                # Verify operation was allowed
                self.assertTrue(can_add, "Should allow operation when DB available and limits not exceeded")
                self.assertEqual(reason, "ok")

        asyncio.run(run_test())

    def test_rate_limit_check_detects_already_added(self):
        """Test: Rate limit check detects already added contacts"""
        async def run_test():
            # Mock SessionLocal to return existing contact
            with patch('src.contact_manager.SessionLocal') as mock_session_local:
                mock_db = AsyncMock()

                # Mock query result - existing contact found
                mock_result = Mock()
                mock_existing = Mock()
                mock_result.scalars.return_value.first.return_value = mock_existing
                mock_db.execute = AsyncMock(return_value=mock_result)

                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_local.return_value = mock_session

                # Call _check_rate_limits - should return already_in_contacts
                can_add, reason = await self.manager._check_rate_limits(
                    telegram_user_id=12345,
                    direction='inbound'
                )

                # Verify contact already added
                self.assertTrue(can_add, "Should return True for already added contacts")
                self.assertEqual(reason, "already_in_contacts")

        asyncio.run(run_test())

    def test_rate_limit_check_enforces_hourly_limit(self):
        """Test: Rate limit check enforces hourly limits"""
        async def run_test():
            # Mock SessionLocal with hourly limit exceeded
            with patch('src.contact_manager.SessionLocal') as mock_session_local:
                mock_db = AsyncMock()

                call_count = 0
                async def execute_side_effect(query):
                    nonlocal call_count
                    call_count += 1

                    mock_result = Mock()
                    if call_count == 1:
                        # First call: check if already added
                        mock_result.scalars.return_value.first.return_value = None
                    elif call_count == 2:
                        # Second call: hourly count (exceeded!)
                        mock_result.scalar.return_value = 999  # Way over limit

                    return mock_result

                mock_db.execute = AsyncMock(side_effect=execute_side_effect)

                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_local.return_value = mock_session

                # Call _check_rate_limits - should deny due to hourly limit
                can_add, reason = await self.manager._check_rate_limits(
                    telegram_user_id=12345,
                    direction='inbound'
                )

                # Verify hourly limit enforced
                self.assertFalse(can_add, "Should deny when hourly limit exceeded")
                self.assertEqual(reason, "hourly_limit_inbound")

        asyncio.run(run_test())

    def test_rate_limit_check_enforces_daily_limit(self):
        """Test: Rate limit check enforces daily limits"""
        async def run_test():
            # Mock SessionLocal with daily limit exceeded
            with patch('src.contact_manager.SessionLocal') as mock_session_local:
                mock_db = AsyncMock()

                call_count = 0
                async def execute_side_effect(query):
                    nonlocal call_count
                    call_count += 1

                    mock_result = Mock()
                    if call_count == 1:
                        # First call: check if already added
                        mock_result.scalars.return_value.first.return_value = None
                    elif call_count == 2:
                        # Second call: hourly count (under limit)
                        mock_result.scalar.return_value = 0
                    elif call_count == 3:
                        # Third call: daily count (exceeded!)
                        mock_result.scalar.return_value = 999

                    return mock_result

                mock_db.execute = AsyncMock(side_effect=execute_side_effect)

                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_local.return_value = mock_session

                # Call _check_rate_limits - should deny due to daily limit
                can_add, reason = await self.manager._check_rate_limits(
                    telegram_user_id=12345,
                    direction='inbound'
                )

                # Verify daily limit enforced
                self.assertFalse(can_add, "Should deny when daily limit exceeded")
                self.assertEqual(reason, "daily_limit_inbound")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
