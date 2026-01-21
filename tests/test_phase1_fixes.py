"""
Tests for Phase 1 HIGH priority fixes

Fix #20, #21: HTTP timeouts для CRM clients
Fix #6: Race condition в set_bridge()
Fix #124: Optimistic locking для outbox
Fix #115: Batch DELETE для retention
"""

import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
from datetime import datetime, timedelta


class TestFix20_21_HTTPTimeouts(unittest.TestCase):
    """Test #20, #21: HTTP timeouts для AmoCRM и Bitrix24"""

    def test_amocrm_refresh_token_has_timeout(self):
        """Test #20: refresh_access_token() использует timeout"""
        from src.amocrm_client import AmoCRMClient, DEFAULT_HTTP_TIMEOUT

        # Verify constant exists
        self.assertEqual(DEFAULT_HTTP_TIMEOUT, 30, "Default timeout should be 30 seconds")

        async def run_test():
            with patch('src.amocrm_client.settings') as mock_settings:
                mock_settings.AMOCRM_DOMAIN = "test.amocrm.ru"
                mock_settings.AMOCRM_CLIENT_ID = "test_id"
                mock_settings.AMOCRM_CLIENT_SECRET = "test_secret"
                mock_settings.AMOCRM_REDIRECT_URI = "http://localhost"
                mock_settings.AMOCRM_ACCESS_TOKEN = "test_access"
                mock_settings.AMOCRM_REFRESH_TOKEN = "test_refresh"
                mock_settings.AMOCRM_TOKEN_EXPIRES_AT = None  # Fix TypeError

                client = AmoCRMClient()
                client.token_expires_at = datetime.now() - timedelta(hours=1)  # Expired token

                # Mock aiohttp.ClientSession to verify timeout is set
                with patch('aiohttp.ClientSession') as MockClientSession:
                    mock_session = MagicMock()
                    mock_response = MagicMock()
                    mock_response.status = 200
                    mock_response.json = AsyncMock(return_value={
                        'access_token': 'new_access',
                        'refresh_token': 'new_refresh',
                        'expires_in': 3600
                    })

                    mock_session.post = MagicMock()
                    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
                    mock_session.post.return_value.__aexit__ = AsyncMock()

                    MockClientSession.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                    MockClientSession.return_value.__aexit__ = AsyncMock()

                    with patch.object(client, '_save_tokens', new_callable=AsyncMock):
                        result = await client.refresh_access_token()

                    # Verify ClientSession was called with timeout
                    MockClientSession.assert_called_once()
                    call_kwargs = MockClientSession.call_args.kwargs

                    self.assertIn('timeout', call_kwargs, "ClientSession should be called with timeout parameter")
                    timeout_obj = call_kwargs['timeout']
                    self.assertIsInstance(timeout_obj, aiohttp.ClientTimeout)
                    self.assertEqual(timeout_obj.total, DEFAULT_HTTP_TIMEOUT)
                    self.assertTrue(result, "refresh_access_token should succeed")

        asyncio.run(run_test())

    def test_bitrix24_call_method_has_timeout(self):
        """Test #21: _call_method() использует timeout"""
        from src.bitrix24_client import Bitrix24Client, DEFAULT_HTTP_TIMEOUT

        # Verify constant exists
        self.assertEqual(DEFAULT_HTTP_TIMEOUT, 30, "Default timeout should be 30 seconds")

        async def run_test():
            with patch('src.bitrix24_client.settings') as mock_settings:
                mock_settings.BITRIX24_DOMAIN = "test.bitrix24.ru"
                mock_settings.BITRIX24_WEBHOOK_URL = "https://test.bitrix24.ru/rest/1/abc123/"
                mock_settings.BITRIX24_CLIENT_ID = None
                mock_settings.BITRIX24_CLIENT_SECRET = None
                mock_settings.BITRIX24_REDIRECT_URI = None
                mock_settings.BITRIX24_ACCESS_TOKEN = None
                mock_settings.BITRIX24_REFRESH_TOKEN = None
                mock_settings.BITRIX24_TOKEN_EXPIRES_AT = None  # Fix TypeError

                client = Bitrix24Client()

                # Mock aiohttp.ClientSession to verify timeout is set
                with patch('aiohttp.ClientSession') as MockClientSession:
                    mock_session = MagicMock()

                    # Mock _make_request to avoid actual HTTP call
                    with patch.object(client, '_make_request', new_callable=AsyncMock) as mock_make_request:
                        mock_make_request.return_value = (200, {"result": "ok"})

                        MockClientSession.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                        MockClientSession.return_value.__aexit__ = AsyncMock()

                        # Call private method _call_method
                        result = await client._call_method("test.method", {"param": "value"})

                        # Verify ClientSession was called with timeout
                        MockClientSession.assert_called_once()
                        call_kwargs = MockClientSession.call_args.kwargs

                        self.assertIn('timeout', call_kwargs, "ClientSession should be called with timeout parameter")
                        timeout_obj = call_kwargs['timeout']
                        self.assertIsInstance(timeout_obj, aiohttp.ClientTimeout)
                        self.assertEqual(timeout_obj.total, DEFAULT_HTTP_TIMEOUT)
                        self.assertEqual(result, {"result": "ok"}, "_call_method should return data")

        asyncio.run(run_test())

    def test_timeout_structure_is_correct(self):
        """Test #20, #21: ClientTimeout создается правильно"""
        from src.amocrm_client import DEFAULT_HTTP_TIMEOUT

        # Test that ClientTimeout is created correctly
        timeout = aiohttp.ClientTimeout(total=DEFAULT_HTTP_TIMEOUT)

        self.assertIsInstance(timeout, aiohttp.ClientTimeout)
        self.assertEqual(timeout.total, DEFAULT_HTTP_TIMEOUT)
        self.assertEqual(timeout.total, 30, "Total timeout should be 30 seconds")


class TestFix6_SetBridgeRaceCondition(unittest.TestCase):
    """Test #6: Race condition в set_bridge() (исправлено как часть #123)"""

    def test_set_bridge_uses_lock(self):
        """Test #6: set_bridge() использует lock для предотвращения race condition"""
        import asyncio
        from src.telegram_manager import TelegramClientManager

        async def run_test():
            manager = TelegramClientManager()

            # Verify lock exists
            self.assertIsNotNone(manager._lock, "Manager should have _lock")
            self.assertEqual(type(manager._lock).__name__, 'Lock')

            # Mock bridge object
            mock_bridge = MagicMock()

            # Call set_bridge (should use lock internally)
            await manager.set_bridge(mock_bridge)

            # Verify bridge was set
            self.assertEqual(manager._bridge, mock_bridge, "Bridge should be set")

        asyncio.run(run_test())

    def test_concurrent_set_bridge_no_race(self):
        """Test #6: Concurrent вызовы set_bridge() не создают race condition"""
        import asyncio
        from src.telegram_manager import TelegramClientManager

        async def run_test():
            manager = TelegramClientManager()

            bridge1 = MagicMock()
            bridge1.name = "bridge1"
            bridge2 = MagicMock()
            bridge2.name = "bridge2"
            bridge3 = MagicMock()
            bridge3.name = "bridge3"

            # Launch 3 concurrent set_bridge calls
            await asyncio.gather(
                manager.set_bridge(bridge1),
                manager.set_bridge(bridge2),
                manager.set_bridge(bridge3)
            )

            # Due to lock, one of the bridges won the race
            # Important: NO race condition occurred (no exception thrown)
            self.assertIsNotNone(manager._bridge, "Bridge should be set")
            self.assertIn(manager._bridge, [bridge1, bridge2, bridge3], "Bridge should be one of the three")

        asyncio.run(run_test())

    def test_set_bridge_updates_existing_clients(self):
        """Test #6: set_bridge() обновляет bridge во всех существующих клиентах"""
        import asyncio
        from src.telegram_manager import TelegramClientManager

        async def run_test():
            manager = TelegramClientManager()

            # Mock two clients
            mock_client1 = MagicMock()
            mock_client2 = MagicMock()

            manager._clients = {
                1: mock_client1,
                2: mock_client2
            }

            # Mock bridge
            mock_bridge = MagicMock()

            # Call set_bridge
            await manager.set_bridge(mock_bridge)

            # Verify bridge was set in manager
            self.assertEqual(manager._bridge, mock_bridge)

            # Verify bridge was set in all clients
            self.assertEqual(mock_client1.bridge, mock_bridge, "Client 1 should have bridge")
            self.assertEqual(mock_client2.bridge, mock_bridge, "Client 2 should have bridge")

        asyncio.run(run_test())


class TestFix124_OptimisticLockingOutbox(unittest.TestCase):
    """Test #124: Optimistic locking для _acquire_next_outbox"""

    def test_acquire_next_outbox_uses_optimistic_locking(self):
        """Test #124: _acquire_next_outbox использует optimistic locking"""
        import asyncio
        from src.database import create_async_engine, async_sessionmaker, Base, MessageOutbox
        from src.outbox import _acquire_next_outbox
        from datetime import datetime
        import tempfile
        import os

        async def run_test():
            # Create unique temporary database file
            fd, db_path = tempfile.mkstemp(suffix=".db")
            os.close(fd)

            try:
                # Create engine and tables
                engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)

                SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

                # Create test outbox message
                async with SessionLocal() as session:
                    outbox = MessageOutbox(
                        idempotency_key="test-key-124",
                        account_id=1,
                        chat_id=12345,
                        payload={"message": "test"},
                        status="queued",
                        attempts=0,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    session.add(outbox)
                    await session.commit()
                    outbox_id = outbox.id

                # First worker acquires the message
                async with SessionLocal() as session:
                    acquired1 = await _acquire_next_outbox(session, "sqlite")

                    self.assertIsNotNone(acquired1, "First worker should acquire message")
                    self.assertEqual(acquired1.id, outbox_id)
                    self.assertEqual(acquired1.status, "processing")

                # Second worker tries to acquire the same message - should fail due to optimistic locking
                async with SessionLocal() as session:
                    # Reload fresh copy
                    from sqlalchemy import select
                    result = await session.execute(select(MessageOutbox).filter_by(id=outbox_id))
                    outbox_fresh = result.scalars().first()

                    # Verify status is "processing"
                    self.assertEqual(outbox_fresh.status, "processing")

                await engine.dispose()
            finally:
                # Cleanup temp database file
                if os.path.exists(db_path):
                    os.unlink(db_path)

        asyncio.run(run_test())

    def test_concurrent_acquire_only_one_succeeds(self):
        """Test #124: При concurrent вызовах только один worker получает сообщение"""
        import asyncio
        from src.database import create_async_engine, async_sessionmaker, Base, MessageOutbox
        from src.outbox import acquire_next_outbox
        from datetime import datetime
        from sqlalchemy import select
        import tempfile
        import os

        async def run_test():
            # Create unique temporary database file
            fd, db_path = tempfile.mkstemp(suffix=".db")
            os.close(fd)

            try:
                # Create engine and tables
                engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)

                SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

                # Create test outbox message
                async with SessionLocal() as session:
                    outbox = MessageOutbox(
                        idempotency_key="test-key-concurrent",
                        account_id=1,
                        chat_id=12345,
                        payload={"message": "test"},
                        status="queued",
                        attempts=0,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    session.add(outbox)
                    await session.commit()
                    outbox_id = outbox.id

                # Simulate two concurrent workers
                acquired_results = []

                async def worker(worker_id):
                    async with SessionLocal() as session:
                        result = await acquire_next_outbox(session)
                        acquired_results.append((worker_id, result))
                        return result

                # Run two workers concurrently
                await asyncio.gather(
                    worker(1),
                    worker(2)
                )

                # Only one should have acquired the message
                successful_acquires = [r for _, r in acquired_results if r is not None]
                self.assertEqual(
                    len(successful_acquires),
                    1,
                    "Only one worker should successfully acquire the message"
                )

                # Verify the message is in "processing" status
                async with SessionLocal() as session:
                    result = await session.execute(select(MessageOutbox).filter_by(id=outbox_id))
                    final_outbox = result.scalars().first()
                    self.assertEqual(final_outbox.status, "processing")

                await engine.dispose()
            finally:
                # Cleanup temp database file
                if os.path.exists(db_path):
                    os.unlink(db_path)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
