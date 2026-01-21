"""
Tests for Contact Manager critical fixes.

Fixes tested:
- #153: _recent_adds modifies with proper locking (prevents race conditions)
- #178: Cleanup task for per-user locks (prevents memory leak)
- #159: Check is_connected() before Telegram API calls

These tests verify that critical Contact Manager fixes work correctly.
"""

import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


class TestContactManagerFix153(unittest.TestCase):
    """Test #153: _recent_adds должен быть защищен от race conditions"""

    def test_recent_adds_protected_by_lock(self):
        """Test #153: Concurrent доступ к _recent_adds должен быть thread-safe"""
        import asyncio
        from src.contact_manager import ContactAddCircuitBreaker

        async def run_test():
            circuit_breaker = ContactAddCircuitBreaker()

            # Simulate 10 concurrent record_add_attempt calls
            tasks = [circuit_breaker.record_add_attempt() for _ in range(10)]
            await asyncio.gather(*tasks)

            # All 10 should be recorded
            # Check by triggering burst limit check
            can_proceed, reason = await circuit_breaker.check_burst_limit()

            # Should fail because we have 10 adds (> MAX_BURST of 5)
            self.assertFalse(can_proceed)
            self.assertEqual(reason, "burst_limit_exceeded")

        asyncio.run(run_test())

    def test_burst_limit_race_condition(self):
        """Test #153: Race condition при concurrent вызовах check_burst_limit"""
        import asyncio
        from src.contact_manager import ContactAddCircuitBreaker

        async def run_test():
            circuit_breaker = ContactAddCircuitBreaker()

            # Add exactly MAX_BURST-1 entries
            for _ in range(circuit_breaker.MAX_BURST - 1):
                await circuit_breaker.record_add_attempt()

            # Now do 2 concurrent checks - both should see same state
            task1 = circuit_breaker.check_burst_limit()
            task2 = circuit_breaker.check_burst_limit()

            results = await asyncio.gather(task1, task2)

            # Both should return same result (no race condition)
            self.assertEqual(results[0], results[1])

        asyncio.run(run_test())

    def test_cleanup_old_entries_during_record(self):
        """Test #153: Старые записи должны удаляться при record_add_attempt"""
        import asyncio
        from src.contact_manager import ContactAddCircuitBreaker
        from datetime import datetime, timedelta

        async def run_test():
            circuit_breaker = ContactAddCircuitBreaker()

            # Add entries that are older than 60 seconds
            now = datetime.utcnow()
            old_time = now - timedelta(seconds=70)

            # Manually add old entries (bypass record_add_attempt)
            circuit_breaker._recent_adds = [old_time] * 10

            # Record new attempt - should cleanup old entries
            await circuit_breaker.record_add_attempt()

            # Check burst limit
            can_proceed, reason = await circuit_breaker.check_burst_limit()

            # Should pass because old entries were cleaned up
            self.assertTrue(can_proceed)
            self.assertEqual(reason, "ok")

        asyncio.run(run_test())


class TestContactManagerFix178(unittest.TestCase):
    """Test #178: Cleanup task для per-user locks должен запускаться"""

    def test_cleanup_task_starts(self):
        """Test #178: start_cleanup_task() должен создавать asyncio.Task"""
        import asyncio
        from src.contact_manager import PerUserLockManager

        async def run_test():
            lock_mgr = PerUserLockManager()

            # Start cleanup task
            await lock_mgr.start_cleanup_task()

            # Verify task was created
            self.assertIsNotNone(lock_mgr._cleanup_task)
            self.assertFalse(lock_mgr._cleanup_task.done())

            # Cancel task for cleanup
            if lock_mgr._cleanup_task:
                lock_mgr._cleanup_task.cancel()
                try:
                    await lock_mgr._cleanup_task
                except asyncio.CancelledError:
                    pass

        asyncio.run(run_test())

    def test_cleanup_removes_stale_locks(self):
        """Test #178: cleanup_stale_locks() должен удалять неиспользуемые locks"""
        import asyncio
        from src.contact_manager import PerUserLockManager
        from datetime import datetime, timedelta

        async def run_test():
            lock_mgr = PerUserLockManager(lock_ttl_seconds=60)

            # Create locks for 3 users
            lock1 = await lock_mgr.get_lock(111)
            lock2 = await lock_mgr.get_lock(222)
            lock3 = await lock_mgr.get_lock(333)

            # Verify 3 locks exist
            self.assertEqual(len(lock_mgr._locks), 3)

            # Manually set last_used to old time for user 111
            old_time = datetime.utcnow() - timedelta(seconds=120)
            lock_mgr._lock_last_used[111] = old_time

            # Run cleanup
            await lock_mgr.cleanup_stale_locks()

            # User 111 lock should be removed
            self.assertNotIn(111, lock_mgr._locks)
            self.assertNotIn(111, lock_mgr._lock_last_used)

            # Users 222 and 333 should still exist
            self.assertIn(222, lock_mgr._locks)
            self.assertIn(333, lock_mgr._locks)

        asyncio.run(run_test())

    def test_cleanup_does_not_remove_held_locks(self):
        """Test #178: cleanup НЕ должен удалять locks, которые сейчас удерживаются"""
        import asyncio
        from src.contact_manager import PerUserLockManager
        from datetime import datetime, timedelta

        async def run_test():
            lock_mgr = PerUserLockManager(lock_ttl_seconds=60)

            # Get lock for user
            lock = await lock_mgr.get_lock(444)

            # Manually set last_used to old time
            old_time = datetime.utcnow() - timedelta(seconds=120)
            lock_mgr._lock_last_used[444] = old_time

            # Hold the lock
            async with lock:
                # Run cleanup while lock is held
                await lock_mgr.cleanup_stale_locks()

                # Lock should NOT be removed (still held)
                self.assertIn(444, lock_mgr._locks)

            # After releasing, lock should still exist (just cleaned up once)
            self.assertIn(444, lock_mgr._locks)

        asyncio.run(run_test())

    def test_contact_manager_initialize_starts_cleanup(self):
        """Test #178: ContactManager.initialize() должен запускать cleanup task"""
        import asyncio
        from src.contact_manager import ContactManager

        async def run_test():
            contact_mgr = ContactManager()

            # Before initialize, cleanup task should not exist
            self.assertIsNone(contact_mgr._lock_manager._cleanup_task)

            # Initialize
            await contact_mgr.initialize()

            # After initialize, cleanup task should be running
            self.assertIsNotNone(contact_mgr._lock_manager._cleanup_task)
            self.assertFalse(contact_mgr._lock_manager._cleanup_task.done())

            # Initialize should be idempotent (second call does nothing)
            await contact_mgr.initialize()

            # Cancel task for cleanup
            if contact_mgr._lock_manager._cleanup_task:
                contact_mgr._lock_manager._cleanup_task.cancel()
                try:
                    await contact_mgr._lock_manager._cleanup_task
                except asyncio.CancelledError:
                    pass

        asyncio.run(run_test())


class TestContactManagerFix159(unittest.TestCase):
    """Test #159: Проверка client.is_connected() перед Telegram API calls"""

    def test_add_to_contacts_checks_is_connected_early(self):
        """Test #159: add_to_contacts_with_protection() проверяет is_connected() в начале"""
        import asyncio
        from unittest.mock import MagicMock, AsyncMock
        from src.contact_manager import ContactManager

        async def run_test():
            contact_mgr = ContactManager()

            # Mock client that is NOT connected
            mock_client = MagicMock()
            mock_client.is_connected = MagicMock(return_value=False)

            # Try to add contact with disconnected client
            success, phone = await contact_mgr.add_to_contacts_with_protection(
                client=mock_client,
                telegram_user_id=12345,
                first_name="Test",
                last_name="User",
                username="testuser",
                direction="inbound",
                source="test"
            )

            # Should fail immediately
            self.assertFalse(success)
            self.assertIsNone(phone)

            # Verify is_connected() was called (early check)
            mock_client.is_connected.assert_called()

        asyncio.run(run_test())

    def test_do_telegram_api_call_checks_is_connected_before_api(self):
        """Test #159: _do_telegram_api_call() проверяет is_connected() перед API"""
        import asyncio
        from unittest.mock import MagicMock, AsyncMock, patch
        from src.contact_manager import ContactManager

        async def run_test():
            contact_mgr = ContactManager()

            # Mock client that becomes disconnected right before API call
            mock_client = MagicMock()
            mock_client.is_connected = MagicMock(return_value=False)
            mock_client.__call__ = AsyncMock()  # Mock the client() call

            # Try to call _do_telegram_api_call directly
            success, phone = await contact_mgr._do_telegram_api_call(
                client=mock_client,
                telegram_user_id=12345,
                first_name="Test",
                last_name="User",
                username="testuser",
                direction="inbound",
                source="test"
            )

            # Should fail without calling Telegram API
            self.assertFalse(success)
            self.assertIsNone(phone)

            # Verify is_connected() was called
            mock_client.is_connected.assert_called()

            # Verify Telegram API was NOT called (client disconnected)
            mock_client.__call__.assert_not_called()

        asyncio.run(run_test())

    def test_connection_check_prevents_flood_errors(self):
        """Test #159: Connection check предотвращает FloodWait errors"""
        import asyncio
        from unittest.mock import MagicMock
        from src.contact_manager import ContactManager

        async def run_test():
            contact_mgr = ContactManager()

            # Simulate scenario: client disconnects between checks
            call_count = [0]

            def is_connected_side_effect():
                call_count[0] += 1
                # First call: connected, second call: disconnected
                return call_count[0] == 1

            mock_client = MagicMock()
            mock_client.is_connected = MagicMock(side_effect=is_connected_side_effect)

            # Mock can_add_contact to allow addition
            async def mock_can_add(direction, user_id):
                return True, "ok"

            contact_mgr.can_add_contact = mock_can_add

            # Try to add contact
            success, phone = await contact_mgr.add_to_contacts_with_protection(
                client=mock_client,
                telegram_user_id=12345,
                first_name="Test",
                last_name="User",
                username="testuser",
                direction="inbound",
                source="test"
            )

            # Should fail at second check (in _do_telegram_api_call)
            self.assertFalse(success)

            # Verify is_connected() was called multiple times (TOCTOU prevention)
            self.assertEqual(mock_client.is_connected.call_count, 2)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
