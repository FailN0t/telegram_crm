"""
Tests for Outbox Worker critical fixes.

Fixes tested:
- #175: Exception handler creates new session (not reuse closed one)

These tests verify that critical Outbox Worker fixes work correctly.
"""

import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# We'll test by mocking database operations


class TestOutboxWorkerFix175(unittest.TestCase):
    """Test #175: Exception handler должен создавать новую session"""

    def test_exception_handler_creates_new_session(self):
        """Test #175: При exception создается НОВАЯ session, не используется закрытая"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def run_test():
            # Import inside to avoid module-level issues
            from src.outbox_worker import OutboxWorker

            worker = OutboxWorker()

            # Mock the database session
            mock_session = MagicMock()
            mock_error_session = MagicMock()

            # Mock outbox object
            mock_outbox = MagicMock()
            mock_outbox.id = 123
            mock_outbox.payload = {"text": "test", "chat_id": 456}
            mock_outbox.attempts = 0
            mock_outbox.account_id = 1

            # Control when to return outbox vs None
            acquire_call_count = [0]

            async def mock_acquire(session):
                acquire_call_count[0] += 1
                if acquire_call_count[0] == 1:
                    return mock_outbox
                # After first call, return None to stop worker loop
                return None

            # Mock process_payload to raise an exception
            async def mock_process_error(session, payload):
                # After exception, set stop event to exit loop
                worker.stop_event.set()
                raise ValueError("Simulated processing error")

            # Mock mark_outbox_result and update_ui_history_status
            async def mock_mark_result(session, outbox, success, error_msg):
                # Verify session is the NEW error_session, not the old closed one
                self.assertIs(session, mock_error_session, "Should use NEW error_session")

            async def mock_update_ui(session, payload, status, error):
                # Verify session is the NEW error_session
                self.assertIs(session, mock_error_session, "Should use NEW error_session")

            # Mock SessionLocal to return different sessions
            session_call_count = [0]

            class MockSessionContext:
                def __init__(self, session):
                    self.session = session

                async def __aenter__(self):
                    return self.session

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass

            def mock_session_local():
                session_call_count[0] += 1
                if session_call_count[0] == 1:
                    # First call: main session (will be closed)
                    return MockSessionContext(mock_session)
                else:
                    # Second call: error handler session (new one)
                    return MockSessionContext(mock_error_session)

            # Apply patches
            with patch('src.outbox_worker.acquire_next_outbox', new=mock_acquire), \
                 patch.object(worker, 'process_payload', new=mock_process_error), \
                 patch('src.outbox_worker.mark_outbox_result', new=mock_mark_result), \
                 patch.object(worker, 'update_ui_history_status', new=mock_update_ui), \
                 patch('src.outbox_worker.SessionLocal', new=mock_session_local):

                # Mock initialize and stop
                worker.initialize = AsyncMock()
                worker.stop = AsyncMock()

                # Run worker (should process one message and hit exception)
                await worker.run()

                # Verify both sessions were created
                self.assertEqual(session_call_count[0], 2, "Should create 2 sessions: main + error handler")

        asyncio.run(run_test())

    def test_exception_handler_marks_outbox_as_failed(self):
        """Test #175: При exception outbox помечается как failed"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def run_test():
            from src.outbox_worker import OutboxWorker

            worker = OutboxWorker()

            # Track calls
            mark_result_calls = []
            update_ui_calls = []

            # Mock outbox
            mock_outbox = MagicMock()
            mock_outbox.id = 789
            mock_outbox.payload = {"text": "test", "chat_id": 999}
            mock_outbox.attempts = 1
            mock_outbox.account_id = 2

            acquire_call_count = [0]

            async def mock_acquire(session):
                acquire_call_count[0] += 1
                if acquire_call_count[0] == 1:
                    return mock_outbox
                return None

            async def mock_process_error(session, payload):
                worker.stop_event.set()
                raise RuntimeError("Database connection lost")

            async def mock_mark_result(session, outbox, success, error_msg):
                mark_result_calls.append({
                    "outbox_id": outbox.id,
                    "success": success,
                    "error_msg": error_msg
                })

            async def mock_update_ui(session, payload, status, error):
                update_ui_calls.append({
                    "payload": payload,
                    "status": status,
                    "error": error
                })

            class MockSessionContext:
                async def __aenter__(self):
                    return MagicMock()

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass

            with patch('src.outbox_worker.acquire_next_outbox', new=mock_acquire), \
                 patch.object(worker, 'process_payload', new=mock_process_error), \
                 patch('src.outbox_worker.mark_outbox_result', new=mock_mark_result), \
                 patch.object(worker, 'update_ui_history_status', new=mock_update_ui), \
                 patch('src.outbox_worker.SessionLocal', return_value=MockSessionContext()):

                worker.initialize = AsyncMock()
                worker.stop = AsyncMock()

                await worker.run()

                # Verify mark_outbox_result was called with success=False
                self.assertEqual(len(mark_result_calls), 1, "Should call mark_outbox_result once")
                self.assertEqual(mark_result_calls[0]["outbox_id"], 789)
                self.assertFalse(mark_result_calls[0]["success"], "Should mark as failed (success=False)")
                self.assertIn("Database connection lost", mark_result_calls[0]["error_msg"])

                # Verify update_ui_history_status was called with status=failed
                self.assertEqual(len(update_ui_calls), 1, "Should call update_ui_history_status once")
                self.assertEqual(update_ui_calls[0]["status"], "failed")
                self.assertIn("Database connection lost", update_ui_calls[0]["error"])

        asyncio.run(run_test())

    def test_no_outbox_no_error_handling(self):
        """Test #175: Если outbox=None, exception handler не пытается пометить"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def run_test():
            from src.outbox_worker import OutboxWorker

            worker = OutboxWorker()

            mark_result_called = [False]

            acquire_call_count = [0]

            async def mock_acquire(session):
                acquire_call_count[0] += 1
                if acquire_call_count[0] == 1:
                    # First call: raise error before returning outbox
                    worker.stop_event.set()
                    raise RuntimeError("Unexpected error during acquire")
                return None

            async def mock_mark_result(session, outbox, success, error_msg):
                mark_result_called[0] = True

            class MockSessionContext:
                async def __aenter__(self):
                    return MagicMock()

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass

            with patch('src.outbox_worker.acquire_next_outbox', new=mock_acquire), \
                 patch('src.outbox_worker.mark_outbox_result', new=mock_mark_result), \
                 patch('src.outbox_worker.SessionLocal', return_value=MockSessionContext()):

                worker.initialize = AsyncMock()
                worker.stop = AsyncMock()

                await worker.run()

                # Verify mark_outbox_result was NOT called (no outbox to mark)
                self.assertFalse(mark_result_called[0], "Should not call mark_outbox_result when outbox is None")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
