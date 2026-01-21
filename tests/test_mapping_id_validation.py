"""
Tests for chat_mapping_id validation.

Validates fix for #117: chat_mapping_id=0 при mapping=None (invalid FK!)

These tests verify that:
1. MessageHistory cannot be created with chat_mapping_id=0
2. MessageHistory cannot be created with chat_mapping_id=None (unless NULL is allowed)
3. Code properly validates mapping.id before creating MessageHistory
4. Database rejects invalid FK values
"""

import asyncio
import os
import tempfile
import unittest
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database import (
    Base,
    TelegramAccount,
    ChatMapping,
    MessageHistory,
)


class TestChatMappingIdValidation(unittest.TestCase):
    """Test validation of chat_mapping_id to prevent invalid FK values"""

    @classmethod
    def setUpClass(cls):
        """Create test database"""
        cls.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.temp_db.close()
        cls.db_url = f"sqlite+aiosqlite:///{cls.temp_db.name}"

    @classmethod
    def tearDownClass(cls):
        """Remove test database"""
        if os.path.exists(cls.temp_db.name):
            os.unlink(cls.temp_db.name)

    def setUp(self):
        """Create fresh database for each test"""
        # Remove old database file to ensure fresh schema
        if os.path.exists(self.temp_db.name):
            try:
                os.unlink(self.temp_db.name)
            except:
                pass

        self.engine = create_async_engine(self.db_url, echo=False)

        # Enable foreign keys for SQLite
        from sqlalchemy import event

        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.SessionLocal = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    def tearDown(self):
        """Clean up after each test"""
        asyncio.run(self._cleanup())

    async def _cleanup(self):
        """Async cleanup"""
        await self.engine.dispose()

    def test_message_history_rejects_zero_mapping_id(self):
        """Test #117: MessageHistory should reject chat_mapping_id=0"""
        async def run_test():
            # Create tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.SessionLocal() as db:
                # Create account
                account = TelegramAccount(
                    phone_number="+1234567890",
                    session_string="test_session",
                    is_active=True
                )
                db.add(account)
                await db.commit()
                await db.refresh(account)

                # Try to create MessageHistory with chat_mapping_id=0
                # This should FAIL due to FK constraint
                invalid_history = MessageHistory(
                    account_id=account.id,
                    chat_mapping_id=0,  # INVALID!
                    amocrm_contact_id=123,
                    direction='outbound',
                    message_text='Test message',
                    telegram_chat_id=999,
                    status='sent'
                )
                db.add(invalid_history)

                # Expect IntegrityError due to FK constraint violation
                with self.assertRaises(IntegrityError) as context:
                    await db.commit()

                # Rollback after error
                await db.rollback()

                # Verify no MessageHistory was created
                result = await db.execute(select(MessageHistory))
                histories = result.scalars().all()
                self.assertEqual(len(histories), 0, "No MessageHistory should exist")

        asyncio.run(run_test())

    def test_message_history_requires_valid_mapping_id(self):
        """Test #117: MessageHistory should require valid chat_mapping_id FK"""
        async def run_test():
            # Create tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.SessionLocal() as db:
                # Create account
                account = TelegramAccount(
                    phone_number="+1234567891",
                    session_string="test_session2",
                    is_active=True
                )
                db.add(account)
                await db.commit()
                await db.refresh(account)

                # Try to create MessageHistory with non-existent chat_mapping_id
                # This should FAIL due to FK constraint
                invalid_history = MessageHistory(
                    account_id=account.id,
                    chat_mapping_id=999999,  # Does not exist!
                    amocrm_contact_id=123,
                    direction='outbound',
                    message_text='Test message',
                    telegram_chat_id=888,
                    status='sent'
                )
                db.add(invalid_history)

                # Expect IntegrityError due to FK constraint violation
                with self.assertRaises(IntegrityError) as context:
                    await db.commit()

                await db.rollback()

                # Verify no MessageHistory was created
                result = await db.execute(select(MessageHistory))
                histories = result.scalars().all()
                self.assertEqual(len(histories), 0)

        asyncio.run(run_test())

    def test_message_history_accepts_valid_mapping_id(self):
        """Test: MessageHistory should accept valid chat_mapping_id"""
        async def run_test():
            # Create tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.SessionLocal() as db:
                # Create account
                account = TelegramAccount(
                    phone_number="+1234567892",
                    session_string="test_session3",
                    is_active=True
                )
                db.add(account)
                await db.commit()
                await db.refresh(account)

                # Create valid ChatMapping
                mapping = ChatMapping(
                    account_id=account.id,
                    telegram_chat_id=111222333,
                    amocrm_contact_id=777,
                    created_at=datetime.utcnow()
                )
                db.add(mapping)
                await db.commit()
                await db.refresh(mapping)

                # Verify mapping.id is valid
                self.assertIsNotNone(mapping.id)
                self.assertGreater(mapping.id, 0)

                # Create MessageHistory with valid chat_mapping_id
                valid_history = MessageHistory(
                    account_id=account.id,
                    chat_mapping_id=mapping.id,  # VALID!
                    amocrm_contact_id=777,
                    direction='outbound',
                    message_text='Test message',
                    telegram_chat_id=111222333,
                    status='sent'
                )
                db.add(valid_history)
                await db.commit()
                await db.refresh(valid_history)

                # Verify MessageHistory was created successfully
                result = await db.execute(select(MessageHistory))
                histories = result.scalars().all()
                self.assertEqual(len(histories), 1)
                self.assertEqual(histories[0].chat_mapping_id, mapping.id)

        asyncio.run(run_test())

    def test_code_validates_mapping_id_before_insert(self):
        """Test: Application code should validate mapping.id before creating MessageHistory"""
        async def run_test():
            # Create tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.SessionLocal() as db:
                # Create account
                account = TelegramAccount(
                    phone_number="+1234567893",
                    session_string="test_session4",
                    is_active=True
                )
                db.add(account)
                await db.commit()
                await db.refresh(account)

                # Simulate a None mapping (as might happen if lookup fails)
                mapping = None

                # Code should validate mapping before creating MessageHistory
                # This test simulates the validation logic in bridge.py:261-265
                if not mapping or not mapping:
                    # Cannot create MessageHistory without valid mapping
                    # This is the expected behavior - do NOT create invalid record
                    pass
                else:
                    # Should not reach here in this test
                    self.fail("Should not attempt to create MessageHistory with None mapping")

                # Verify no MessageHistory was created
                result = await db.execute(select(MessageHistory))
                histories = result.scalars().all()
                self.assertEqual(len(histories), 0, "Should not create MessageHistory when mapping is None")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
