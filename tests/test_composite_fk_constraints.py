"""
Tests for Composite Foreign Key constraints and CASCADE behavior.

Validates fixes for:
- #102: FK constraint on ChatProfile references composite unique key
- #103: FK constraint on UiChat references composite unique key
- #119: FK constraint on MessageOutbox references composite unique key

These tests verify that:
1. FK constraints correctly reference the UNIQUE (account_id, telegram_chat_id) index
2. CASCADE deletes work properly when ChatMapping is deleted
3. Multi-account isolation works correctly
"""

import asyncio
import os
import tempfile
import unittest
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database import (
    Base,
    TelegramAccount,
    ChatMapping,
    ChatProfile,
    MessageOutbox,
    UiChat,
    UiMessageHistory,
)


class TestCompositeForeignKeyConstraints(unittest.TestCase):
    """Test composite FK constraints on (account_id, telegram_chat_id)"""

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

    def test_chat_profile_fk_cascade_delete(self):
        """Test #102: ChatProfile FK references composite unique key and CASCADE works"""
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

                # Create chat mapping
                mapping = ChatMapping(
                    account_id=account.id,
                    telegram_chat_id=123456789,
                    amocrm_contact_id=999,
                    created_at=datetime.utcnow()
                )
                db.add(mapping)
                await db.commit()
                await db.refresh(mapping)

                # Create chat profile referencing the mapping via composite FK
                profile = ChatProfile(
                    account_id=account.id,
                    telegram_chat_id=123456789,
                    tags="test",
                    notes="Test profile",
                    has_consent=True
                )
                db.add(profile)
                await db.commit()
                await db.refresh(profile)

                # Verify profile was created
                result = await db.execute(select(ChatProfile))
                profiles = result.scalars().all()
                self.assertEqual(len(profiles), 1)
                self.assertEqual(profiles[0].telegram_chat_id, 123456789)

                # Delete chat mapping - should CASCADE delete profile
                await db.delete(mapping)
                await db.commit()

                # Verify profile was CASCADE deleted
                result = await db.execute(select(ChatProfile))
                profiles = result.scalars().all()
                self.assertEqual(len(profiles), 0, "ChatProfile should be CASCADE deleted")

        asyncio.run(run_test())

    def test_ui_chat_fk_cascade_delete(self):
        """Test #103: UiChat FK references composite unique key and CASCADE works"""
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

                # Create chat mapping
                mapping = ChatMapping(
                    account_id=account.id,
                    telegram_chat_id=987654321,
                    amocrm_contact_id=888,
                    created_at=datetime.utcnow()
                )
                db.add(mapping)
                await db.commit()
                await db.refresh(mapping)

                # Create UI chat referencing the mapping via composite FK
                ui_chat = UiChat(
                    account_id=account.id,
                    chat_id=987654321,
                    username="testuser",
                    display_name="Test User",
                    last_message="Hello",
                    last_direction="inbound",
                    last_timestamp=datetime.utcnow(),
                    unread_count=1
                )
                db.add(ui_chat)
                await db.commit()
                await db.refresh(ui_chat)

                # Verify UI chat was created
                result = await db.execute(select(UiChat))
                ui_chats = result.scalars().all()
                self.assertEqual(len(ui_chats), 1)
                self.assertEqual(ui_chats[0].chat_id, 987654321)

                # Delete chat mapping - should CASCADE delete UI chat
                await db.delete(mapping)
                await db.commit()

                # Verify UI chat was CASCADE deleted
                result = await db.execute(select(UiChat))
                ui_chats = result.scalars().all()
                self.assertEqual(len(ui_chats), 0, "UiChat should be CASCADE deleted")

        asyncio.run(run_test())

    def test_message_outbox_fk_cascade_delete(self):
        """Test #119: MessageOutbox FK references composite unique key and CASCADE works"""
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

                # Create chat mapping
                mapping = ChatMapping(
                    account_id=account.id,
                    telegram_chat_id=111222333,
                    amocrm_contact_id=777,
                    created_at=datetime.utcnow()
                )
                db.add(mapping)
                await db.commit()
                await db.refresh(mapping)

                # Create message outbox referencing the mapping via composite FK
                outbox = MessageOutbox(
                    idempotency_key="test_key_123",
                    account_id=account.id,
                    chat_id=111222333,
                    payload={"message": "Test message"},
                    status="queued"
                )
                db.add(outbox)
                await db.commit()
                await db.refresh(outbox)

                # Verify outbox was created
                result = await db.execute(select(MessageOutbox))
                outboxes = result.scalars().all()
                self.assertEqual(len(outboxes), 1)
                self.assertEqual(outboxes[0].chat_id, 111222333)

                # Delete chat mapping - should CASCADE delete outbox
                await db.delete(mapping)
                await db.commit()

                # Verify outbox was CASCADE deleted
                result = await db.execute(select(MessageOutbox))
                outboxes = result.scalars().all()
                self.assertEqual(len(outboxes), 0, "MessageOutbox should be CASCADE deleted")

        asyncio.run(run_test())

    def test_ui_message_history_fk_cascade_delete(self):
        """Test: UiMessageHistory FK references composite unique key and CASCADE works"""
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

                # Create chat mapping
                mapping = ChatMapping(
                    account_id=account.id,
                    telegram_chat_id=444555666,
                    amocrm_contact_id=666,
                    created_at=datetime.utcnow()
                )
                db.add(mapping)
                await db.commit()
                await db.refresh(mapping)

                # Create UI message history referencing the mapping via composite FK
                msg = UiMessageHistory(
                    account_id=account.id,
                    chat_id=444555666,
                    direction="outbound",
                    message_text="Test message",
                    status="sent"
                )
                db.add(msg)
                await db.commit()
                await db.refresh(msg)

                # Verify message was created
                result = await db.execute(select(UiMessageHistory))
                messages = result.scalars().all()
                self.assertEqual(len(messages), 1)
                self.assertEqual(messages[0].chat_id, 444555666)

                # Delete chat mapping - should CASCADE delete message
                await db.delete(mapping)
                await db.commit()

                # Verify message was CASCADE deleted
                result = await db.execute(select(UiMessageHistory))
                messages = result.scalars().all()
                self.assertEqual(len(messages), 0, "UiMessageHistory should be CASCADE deleted")

        asyncio.run(run_test())

    def test_multi_account_fk_isolation(self):
        """Test: FK constraints work correctly with multiple accounts (same chat_id, different accounts)"""
        async def run_test():
            # Create tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with self.SessionLocal() as db:
                # Create two accounts
                account1 = TelegramAccount(
                    phone_number="+1111111111",
                    session_string="session1",
                    is_active=True
                )
                account2 = TelegramAccount(
                    phone_number="+2222222222",
                    session_string="session2",
                    is_active=True
                )
                db.add_all([account1, account2])
                await db.commit()
                await db.refresh(account1)
                await db.refresh(account2)

                # Create same chat_id for both accounts (this is the multi-account scenario)
                same_chat_id = 999888777

                mapping1 = ChatMapping(
                    account_id=account1.id,
                    telegram_chat_id=same_chat_id,
                    amocrm_contact_id=100,
                    created_at=datetime.utcnow()
                )
                mapping2 = ChatMapping(
                    account_id=account2.id,
                    telegram_chat_id=same_chat_id,
                    amocrm_contact_id=200,
                    created_at=datetime.utcnow()
                )
                db.add_all([mapping1, mapping2])
                await db.commit()
                await db.refresh(mapping1)
                await db.refresh(mapping2)

                # Create chat profiles for both accounts with same chat_id
                profile1 = ChatProfile(
                    account_id=account1.id,
                    telegram_chat_id=same_chat_id,
                    tags="account1",
                    has_consent=True
                )
                profile2 = ChatProfile(
                    account_id=account2.id,
                    telegram_chat_id=same_chat_id,
                    tags="account2",
                    has_consent=True
                )
                db.add_all([profile1, profile2])
                await db.commit()

                # Verify both profiles exist
                result = await db.execute(select(ChatProfile))
                profiles = result.scalars().all()
                self.assertEqual(len(profiles), 2)

                # Delete mapping1 - should only CASCADE delete profile1
                await db.delete(mapping1)
                await db.commit()

                # Verify only profile1 was deleted
                result = await db.execute(select(ChatProfile))
                profiles = result.scalars().all()
                self.assertEqual(len(profiles), 1, "Only one profile should remain")
                self.assertEqual(profiles[0].account_id, account2.id)
                self.assertEqual(profiles[0].tags, "account2")

                # mapping2 should still exist
                result = await db.execute(select(ChatMapping))
                mappings = result.scalars().all()
                self.assertEqual(len(mappings), 1)
                self.assertEqual(mappings[0].account_id, account2.id)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
