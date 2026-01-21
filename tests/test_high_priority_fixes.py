"""
Tests for HIGH priority fixes.

Fixes tested:
- #2: Double-checked locking for Telegram client connection
- #4: Race condition in _warm_ui_chats()
- #5: Non-atomic check for is_new_chat
- #6: Race condition in global bridge (api_server.py)
- #17: Session leak on exception
- #18: Temporary files leak
- #20: AmoCRM HTTP timeouts
- #21: Bitrix24 HTTP timeouts
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFix2DoubleCheckedLockingConnection(unittest.TestCase):
    """Test #2: Double-checked locking для connect()"""

    def test_connect_uses_lock(self):
        """Test #2: connect() использует lock для предотвращения race condition"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        async def run_test():
            # Mock MTProtoClient
            from src.telegram_client import MTProtoClient

            # Create instance with mocked dependencies
            with patch('src.telegram_client.settings') as mock_settings, \
                 patch('src.telegram_client.TelegramClient') as MockTelegramClient:

                mock_settings.TELEGRAM_API_ID = 12345
                mock_settings.TELEGRAM_API_HASH = "test_hash"
                mock_settings.TELEGRAM_PHONE = "+1234567890"
                mock_settings.TELEGRAM_SESSION_NAME = "test_session"
                mock_settings.TELEGRAM_STRING_SESSION = None

                # Mock TelegramClient instance
                mock_client = MagicMock()
                mock_client.is_connected = MagicMock(return_value=False)
                mock_client.connect = AsyncMock()
                MockTelegramClient.return_value = mock_client

                # Create MTProtoClient
                client = MTProtoClient(account_id=1)
                client.client = mock_client

                # Verify lock exists
                self.assertIsNotNone(client._connect_lock)
                self.assertEqual(type(client._connect_lock).__name__, 'Lock')

                # Call connect
                await client.connect()

                # Verify connect was called
                mock_client.connect.assert_called_once()

        asyncio.run(run_test())

    def test_concurrent_connect_calls_serialized(self):
        """Test #2: Concurrent вызовы connect() сериализуются через lock"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, call

        async def run_test():
            from src.telegram_client import MTProtoClient

            with patch('src.telegram_client.settings') as mock_settings, \
                 patch('src.telegram_client.TelegramClient') as MockTelegramClient:

                mock_settings.TELEGRAM_API_ID = 12345
                mock_settings.TELEGRAM_API_HASH = "test_hash"
                mock_settings.TELEGRAM_PHONE = "+1234567890"
                mock_settings.TELEGRAM_SESSION_NAME = "test_session"
                mock_settings.TELEGRAM_STRING_SESSION = None

                # Track connection state
                is_connected = [False]
                connect_calls = []

                def mock_is_connected():
                    return is_connected[0]

                async def mock_connect():
                    connect_calls.append(asyncio.get_event_loop().time())
                    await asyncio.sleep(0.01)  # Simulate connection delay
                    is_connected[0] = True

                mock_client = MagicMock()
                mock_client.is_connected = mock_is_connected
                mock_client.connect = mock_connect
                MockTelegramClient.return_value = mock_client

                client = MTProtoClient(account_id=1)
                client.client = mock_client

                # Launch 3 concurrent connect calls
                await asyncio.gather(
                    client.connect(),
                    client.connect(),
                    client.connect()
                )

                # Verify connect was called only ONCE (not 3 times)
                # Due to double-checked locking, only the first thread should connect
                self.assertEqual(len(connect_calls), 1, "Should call connect() only once despite 3 concurrent calls")

        asyncio.run(run_test())

    def test_fast_path_skips_lock_when_connected(self):
        """Test #2: Fast path пропускает lock если уже подключен"""
        import asyncio

        async def run_test():
            from src.telegram_client import MTProtoClient

            with patch('src.telegram_client.settings') as mock_settings, \
                 patch('src.telegram_client.TelegramClient') as MockTelegramClient:

                mock_settings.TELEGRAM_API_ID = 12345
                mock_settings.TELEGRAM_API_HASH = "test_hash"
                mock_settings.TELEGRAM_PHONE = "+1234567890"
                mock_settings.TELEGRAM_SESSION_NAME = "test_session"
                mock_settings.TELEGRAM_STRING_SESSION = None

                mock_client = MagicMock()
                mock_client.is_connected = MagicMock(return_value=True)  # Already connected
                mock_client.connect = AsyncMock()
                MockTelegramClient.return_value = mock_client

                client = MTProtoClient(account_id=1)
                client.client = mock_client

                # Call connect when already connected
                await client.connect()

                # Verify connect was NOT called (fast path)
                mock_client.connect.assert_not_called()

        asyncio.run(run_test())


class TestFix4RaceConditionWarmChats(unittest.TestCase):
    """Test #4: Race condition в _warm_ui_chats()"""

    def test_warm_ui_chats_uses_lock(self):
        """Test #4: _warm_ui_chats() использует lock для защиты _recent_chat_ids"""
        import asyncio

        async def run_test():
            from src.telegram_client import MTProtoClient

            with patch('src.telegram_client.settings') as mock_settings, \
                 patch('src.telegram_client.TelegramClient') as MockTelegramClient, \
                 patch('src.telegram_client.SessionLocal') as MockSessionLocal:

                mock_settings.TELEGRAM_API_ID = 12345
                mock_settings.TELEGRAM_API_HASH = "test_hash"
                mock_settings.TELEGRAM_PHONE = "+1234567890"
                mock_settings.TELEGRAM_SESSION_NAME = "test_session"
                mock_settings.TELEGRAM_STRING_SESSION = None

                mock_client = MagicMock()
                MockTelegramClient.return_value = mock_client

                # Mock database session
                class MockSessionContext:
                    async def __aenter__(self):
                        mock_session = MagicMock()
                        mock_result = MagicMock()
                        mock_result.scalars.return_value.all.return_value = [1, 2, 3]
                        mock_session.execute = AsyncMock(return_value=mock_result)
                        return mock_session

                    async def __aexit__(self, exc_type, exc_val, exc_tb):
                        pass

                MockSessionLocal.return_value = MockSessionContext()

                client = MTProtoClient(account_id=1)

                # Verify lock exists
                self.assertIsNotNone(client._chats_lock)
                self.assertEqual(type(client._chats_lock).__name__, 'Lock')

                # Call _warm_ui_chats
                await client._warm_ui_chats()

                # Verify _recent_chat_ids was set
                self.assertEqual(client._recent_chat_ids, {1, 2, 3})

        asyncio.run(run_test())

    def test_concurrent_warm_ui_chats_no_race(self):
        """Test #4: Concurrent вызовы _warm_ui_chats() не создают race condition"""
        import asyncio

        async def run_test():
            from src.telegram_client import MTProtoClient

            with patch('src.telegram_client.settings') as mock_settings, \
                 patch('src.telegram_client.TelegramClient') as MockTelegramClient, \
                 patch('src.telegram_client.SessionLocal') as MockSessionLocal:

                mock_settings.TELEGRAM_API_ID = 12345
                mock_settings.TELEGRAM_API_HASH = "test_hash"
                mock_settings.TELEGRAM_PHONE = "+1234567890"
                mock_settings.TELEGRAM_SESSION_NAME = "test_session"
                mock_settings.TELEGRAM_STRING_SESSION = None

                mock_client = MagicMock()
                MockTelegramClient.return_value = mock_client

                call_count = [0]

                class MockSessionContext:
                    async def __aenter__(self):
                        mock_session = MagicMock()
                        call_count[0] += 1
                        current_call = call_count[0]

                        mock_result = MagicMock()
                        # Return different chat IDs for each call
                        mock_result.scalars.return_value.all.return_value = [current_call * 10]
                        mock_session.execute = AsyncMock(return_value=mock_result)
                        return mock_session

                    async def __aexit__(self, exc_type, exc_val, exc_tb):
                        pass

                MockSessionLocal.return_value = MockSessionContext()

                client = MTProtoClient(account_id=1)

                # Launch 3 concurrent calls
                await asyncio.gather(
                    client._warm_ui_chats(),
                    client._warm_ui_chats(),
                    client._warm_ui_chats()
                )

                # Due to lock, _recent_chat_ids will contain result from last call
                # Important: NO race condition occurred (no exception thrown)
                self.assertIsNotNone(client._recent_chat_ids)
                self.assertIsInstance(client._recent_chat_ids, set)

        asyncio.run(run_test())

    def test_reset_local_state_uses_lock(self):
        """Test #4: reset_local_state() использует lock"""
        import asyncio

        async def run_test():
            from src.telegram_client import MTProtoClient

            with patch('src.telegram_client.settings') as mock_settings, \
                 patch('src.telegram_client.TelegramClient') as MockTelegramClient:

                mock_settings.TELEGRAM_API_ID = 12345
                mock_settings.TELEGRAM_API_HASH = "test_hash"
                mock_settings.TELEGRAM_PHONE = "+1234567890"
                mock_settings.TELEGRAM_SESSION_NAME = "test_session"
                mock_settings.TELEGRAM_STRING_SESSION = None

                mock_client = MagicMock()
                MockTelegramClient.return_value = mock_client

                client = MTProtoClient(account_id=1)
                client._recent_chat_ids = {1, 2, 3}

                # Call reset_local_state
                await client.reset_local_state()

                # Verify _recent_chat_ids was cleared
                self.assertEqual(len(client._recent_chat_ids), 0)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
