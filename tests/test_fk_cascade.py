"""
Test Foreign Key CASCADE behavior.
Tests that when a parent record is deleted, child records are automatically deleted.
"""

import os
import asyncio
import unittest

from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_fk_cascade.db")

from src.database import (
    init_db,
    ensure_default_account,
    SessionLocal,
    ChatMapping,
    ChatProfile,
    MessageOutbox,
    MessageDeliveryAttempt,
    UiMessageHistory,
    UiChat,
    MessageHistory
)


class ForeignKeyCascadeTests(unittest.TestCase):
    """Test suite for FK CASCADE delete behavior."""

    @classmethod
    def setUpClass(cls):
        """Initialize test database."""
        db_path = "test_fk_cascade.db"
        if os.path.exists(db_path):
            os.remove(db_path)

        async def _setup():
            await init_db()
            # Clean all tables
            async with SessionLocal() as session:
                await session.execute(MessageHistory.__table__.delete())
                await session.execute(UiMessageHistory.__table__.delete())
                await session.execute(UiChat.__table__.delete())
                await session.execute(MessageDeliveryAttempt.__table__.delete())
                await session.execute(MessageOutbox.__table__.delete())
                await session.execute(ChatProfile.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

        asyncio.run(_setup())

    def test_cascade_chat_mapping_deletes_message_history(self):
        """Test: Delete ChatMapping -> MessageHistory CASCADE delete."""
        async def _run():
            account_id = await ensure_default_account()
            async with SessionLocal() as session:
                # Clean tables
                await session.execute(MessageHistory.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

                # Create chat mapping
                chat = ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=12345,
                    amocrm_contact_id=999,
                    telegram_username="test_user"
                )
                session.add(chat)
                await session.commit()
                await session.refresh(chat)

                # Create message history linked to chat
                message = MessageHistory(
                    account_id=account_id,
                    chat_mapping_id=chat.id,
                    amocrm_contact_id=999,
                    telegram_chat_id=12345,
                    direction="inbound",
                    message_text="Test message",
                    message_type="text"
                )
                session.add(message)
                await session.commit()
                await session.refresh(message)

                # Verify message exists
                result = await session.execute(
                    select(MessageHistory).filter_by(id=message.id)
                )
                self.assertIsNotNone(result.scalars().first())

                # Delete chat mapping
                await session.delete(chat)
                await session.commit()

                # Verify message was CASCADE deleted
                result = await session.execute(
                    select(MessageHistory).filter_by(id=message.id)
                )
                self.assertIsNone(result.scalars().first())

        asyncio.run(_run())

    def test_cascade_chat_mapping_deletes_chat_profile(self):
        """Test: Delete ChatMapping -> ChatProfile CASCADE delete."""
        async def _run():
            account_id = await ensure_default_account()
            async with SessionLocal() as session:
                # Clean tables
                await session.execute(ChatProfile.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

                # Create chat mapping
                chat = ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=67890,
                    amocrm_contact_id=888,
                    telegram_username="profile_user"
                )
                session.add(chat)
                await session.commit()
                await session.refresh(chat)

                # Create chat profile linked to chat
                profile = ChatProfile(
                    account_id=account_id,
                    telegram_chat_id=67890,
                    tags="vip,important",
                    notes="Test notes"
                )
                session.add(profile)
                await session.commit()
                await session.refresh(profile)

                # Verify profile exists
                result = await session.execute(
                    select(ChatProfile).filter_by(id=profile.id)
                )
                self.assertIsNotNone(result.scalars().first())

                # Delete chat mapping
                await session.delete(chat)
                await session.commit()

                # Verify profile was CASCADE deleted
                result = await session.execute(
                    select(ChatProfile).filter_by(id=profile.id)
                )
                self.assertIsNone(result.scalars().first())

        asyncio.run(_run())

    def test_cascade_outbox_deletes_delivery_attempts(self):
        """Test: Delete MessageOutbox -> MessageDeliveryAttempt CASCADE delete."""
        async def _run():
            account_id = await ensure_default_account()
            async with SessionLocal() as session:
                # Clean tables
                await session.execute(MessageDeliveryAttempt.__table__.delete())
                await session.execute(MessageOutbox.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

                # Create chat mapping
                chat = ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=11111,
                    amocrm_contact_id=777,
                    telegram_username="outbox_user"
                )
                session.add(chat)
                await session.commit()

                # Create outbox message
                outbox = MessageOutbox(
                    idempotency_key="test-cascade-1",
                    account_id=account_id,
                    chat_id=11111,
                    payload={"text": "test"},
                    status="failed"
                )
                session.add(outbox)
                await session.commit()
                await session.refresh(outbox)

                # Create delivery attempts
                attempt1 = MessageDeliveryAttempt(
                    outbox_id=outbox.id,
                    attempt=1,
                    status="failed",
                    error_message="Error 1"
                )
                attempt2 = MessageDeliveryAttempt(
                    outbox_id=outbox.id,
                    attempt=2,
                    status="failed",
                    error_message="Error 2"
                )
                session.add_all([attempt1, attempt2])
                await session.commit()

                # Verify attempts exist
                result = await session.execute(
                    select(MessageDeliveryAttempt).filter_by(outbox_id=outbox.id)
                )
                attempts = result.scalars().all()
                self.assertEqual(len(attempts), 2)

                # Delete outbox message
                await session.delete(outbox)
                await session.commit()

                # Verify delivery attempts were CASCADE deleted
                result = await session.execute(
                    select(MessageDeliveryAttempt).filter_by(outbox_id=outbox.id)
                )
                attempts = result.scalars().all()
                self.assertEqual(len(attempts), 0)

        asyncio.run(_run())

    def test_cascade_chat_mapping_deletes_outbox(self):
        """Test: Delete ChatMapping -> MessageOutbox CASCADE delete."""
        async def _run():
            account_id = await ensure_default_account()
            async with SessionLocal() as session:
                # Clean tables
                await session.execute(MessageDeliveryAttempt.__table__.delete())
                await session.execute(MessageOutbox.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

                # Create chat mapping
                chat = ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=22222,
                    amocrm_contact_id=666,
                    telegram_username="cascade_user"
                )
                session.add(chat)
                await session.commit()

                # Create outbox messages
                outbox1 = MessageOutbox(
                    idempotency_key="cascade-outbox-1",
                    account_id=account_id,
                    chat_id=22222,
                    payload={"text": "message 1"},
                    status="queued"
                )
                outbox2 = MessageOutbox(
                    idempotency_key="cascade-outbox-2",
                    account_id=account_id,
                    chat_id=22222,
                    payload={"text": "message 2"},
                    status="sent"
                )
                session.add_all([outbox1, outbox2])
                await session.commit()

                # Verify outbox messages exist
                result = await session.execute(
                    select(MessageOutbox).filter_by(chat_id=22222)
                )
                outbox_messages = result.scalars().all()
                self.assertEqual(len(outbox_messages), 2)

                # Delete chat mapping
                await session.delete(chat)
                await session.commit()

                # Verify outbox messages were CASCADE deleted
                result = await session.execute(
                    select(MessageOutbox).filter_by(chat_id=22222)
                )
                outbox_messages = result.scalars().all()
                self.assertEqual(len(outbox_messages), 0)

        asyncio.run(_run())

    def test_cascade_chat_mapping_deletes_ui_message_history(self):
        """Test: Delete ChatMapping -> UiMessageHistory CASCADE delete."""
        async def _run():
            account_id = await ensure_default_account()
            async with SessionLocal() as session:
                # Clean tables
                await session.execute(UiMessageHistory.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

                # Create chat mapping
                chat = ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=33333,
                    amocrm_contact_id=555,
                    telegram_username="ui_user"
                )
                session.add(chat)
                await session.commit()

                # Create UI message history
                ui_msg = UiMessageHistory(
                    account_id=account_id,
                    chat_id=33333,
                    direction="outbound",
                    message_text="UI test message",
                    message_type="text"
                )
                session.add(ui_msg)
                await session.commit()
                await session.refresh(ui_msg)

                # Verify UI message exists
                result = await session.execute(
                    select(UiMessageHistory).filter_by(id=ui_msg.id)
                )
                self.assertIsNotNone(result.scalars().first())

                # Delete chat mapping
                await session.delete(chat)
                await session.commit()

                # Verify UI message was CASCADE deleted
                result = await session.execute(
                    select(UiMessageHistory).filter_by(id=ui_msg.id)
                )
                self.assertIsNone(result.scalars().first())

        asyncio.run(_run())

    def test_cascade_chat_mapping_deletes_ui_chat(self):
        """Test: Delete ChatMapping -> UiChat CASCADE delete."""
        async def _run():
            account_id = await ensure_default_account()
            async with SessionLocal() as session:
                # Clean tables
                await session.execute(UiChat.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

                # Create chat mapping
                chat = ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=44444,
                    amocrm_contact_id=444,
                    telegram_username="ui_chat_user"
                )
                session.add(chat)
                await session.commit()

                # Create UI chat
                ui_chat = UiChat(
                    account_id=account_id,
                    chat_id=44444,
                    username="ui_chat_user",
                    display_name="Test User"
                )
                session.add(ui_chat)
                await session.commit()
                await session.refresh(ui_chat)

                # Verify UI chat exists
                result = await session.execute(
                    select(UiChat).filter_by(id=ui_chat.id)
                )
                self.assertIsNotNone(result.scalars().first())

                # Delete chat mapping
                await session.delete(chat)
                await session.commit()

                # Verify UI chat was CASCADE deleted
                result = await session.execute(
                    select(UiChat).filter_by(id=ui_chat.id)
                )
                self.assertIsNone(result.scalars().first())

        asyncio.run(_run())

    def test_cascade_full_chain(self):
        """Test: Delete ChatMapping cascades through entire chain."""
        async def _run():
            account_id = await ensure_default_account()
            async with SessionLocal() as session:
                # Clean all tables
                await session.execute(MessageHistory.__table__.delete())
                await session.execute(UiMessageHistory.__table__.delete())
                await session.execute(UiChat.__table__.delete())
                await session.execute(MessageDeliveryAttempt.__table__.delete())
                await session.execute(MessageOutbox.__table__.delete())
                await session.execute(ChatProfile.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

                # Create chat mapping
                chat = ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=99999,
                    amocrm_contact_id=999,
                    telegram_username="full_chain_user"
                )
                session.add(chat)
                await session.commit()
                await session.refresh(chat)

                # Create all related records
                profile = ChatProfile(
                    account_id=account_id,
                    telegram_chat_id=99999,
                    tags="test"
                )
                message_history = MessageHistory(
                    account_id=account_id,
                    chat_mapping_id=chat.id,
                    amocrm_contact_id=999,
                    telegram_chat_id=99999,
                    direction="inbound",
                    message_text="Test"
                )
                outbox = MessageOutbox(
                    idempotency_key="full-chain-1",
                    account_id=account_id,
                    chat_id=99999,
                    payload={"text": "test"},
                    status="queued"
                )
                ui_msg = UiMessageHistory(
                    account_id=account_id,
                    chat_id=99999,
                    direction="inbound",
                    message_text="UI Test"
                )
                ui_chat = UiChat(
                    account_id=account_id,
                    chat_id=99999,
                    username="full_chain_user"
                )
                session.add_all([profile, message_history, outbox, ui_msg, ui_chat])
                await session.commit()
                await session.refresh(outbox)

                # Create delivery attempt
                attempt = MessageDeliveryAttempt(
                    outbox_id=outbox.id,
                    attempt=1,
                    status="failed"
                )
                session.add(attempt)
                await session.commit()

                # Verify all records exist
                self.assertEqual(
                    len((await session.execute(select(ChatProfile).filter_by(telegram_chat_id=99999))).scalars().all()), 1
                )
                self.assertEqual(
                    len((await session.execute(select(MessageHistory).filter_by(chat_mapping_id=chat.id))).scalars().all()), 1
                )
                self.assertEqual(
                    len((await session.execute(select(MessageOutbox).filter_by(chat_id=99999))).scalars().all()), 1
                )
                self.assertEqual(
                    len((await session.execute(select(MessageDeliveryAttempt).filter_by(outbox_id=outbox.id))).scalars().all()), 1
                )
                self.assertEqual(
                    len((await session.execute(select(UiMessageHistory).filter_by(chat_id=99999))).scalars().all()), 1
                )
                self.assertEqual(
                    len((await session.execute(select(UiChat).filter_by(chat_id=99999))).scalars().all()), 1
                )

                # Delete chat mapping - should CASCADE delete everything
                await session.delete(chat)
                await session.commit()

                # Verify all related records were CASCADE deleted
                self.assertEqual(
                    len((await session.execute(select(ChatProfile).filter_by(telegram_chat_id=99999))).scalars().all()), 0
                )
                self.assertEqual(
                    len((await session.execute(select(MessageHistory).filter_by(telegram_chat_id=99999))).scalars().all()), 0
                )
                self.assertEqual(
                    len((await session.execute(select(MessageOutbox).filter_by(chat_id=99999))).scalars().all()), 0
                )
                self.assertEqual(
                    len((await session.execute(select(MessageDeliveryAttempt))).scalars().all()), 0
                )
                self.assertEqual(
                    len((await session.execute(select(UiMessageHistory).filter_by(chat_id=99999))).scalars().all()), 0
                )
                self.assertEqual(
                    len((await session.execute(select(UiChat).filter_by(chat_id=99999))).scalars().all()), 0
                )

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
