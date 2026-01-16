import os
import asyncio
import unittest

from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_outbox.db")

from src.database import (
    init_db,
    ensure_default_account,
    SessionLocal,
    ChatMapping,
    MessageOutbox,
    MessageDeliveryAttempt
)
from src.outbox import acquire_next_outbox, mark_outbox_non_retryable


class OutboxModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_path = "test_outbox.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        async def _setup():
            await init_db()
            async with SessionLocal() as session:
                await session.execute(MessageDeliveryAttempt.__table__.delete())
                await session.execute(MessageOutbox.__table__.delete())
                await session.commit()

        asyncio.run(_setup())

    def test_outbox_insert_and_attempt(self):
        async def _run():
            account_id = await ensure_default_account()
            async with SessionLocal() as session:
                await session.execute(ChatMapping.__table__.delete())
                session.add(ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=123,
                    amocrm_contact_id=1230,
                    telegram_username="demo"
                ))
                await session.commit()
                outbox = MessageOutbox(
                    idempotency_key="key-1",
                    account_id=account_id,
                    chat_id=123,
                    payload={"text": "hello"},
                    status="queued"
                )
                session.add(outbox)
                await session.commit()
                await session.refresh(outbox)

                attempt = MessageDeliveryAttempt(
                    outbox_id=outbox.id,
                    attempt=1,
                    status="failed",
                    error_message="test"
                )
                session.add(attempt)
                await session.commit()

                result = await session.execute(
                    select(MessageOutbox).filter_by(id=outbox.id)
                )
                fetched = result.scalars().first()
                self.assertIsNotNone(fetched)
                self.assertEqual(fetched.payload.get("text"), "hello")

                result = await session.execute(
                    select(MessageDeliveryAttempt).filter_by(outbox_id=outbox.id)
                )
                attempts = result.scalars().all()
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0].error_message, "test")

        asyncio.run(_run())

    def test_outbox_ordering_per_chat(self):
        async def _run():
            account_id = await ensure_default_account()
            async with SessionLocal() as session:
                await session.execute(MessageDeliveryAttempt.__table__.delete())
                await session.execute(MessageOutbox.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

                session.add_all([
                    ChatMapping(
                        account_id=account_id,
                        telegram_chat_id=10,
                        amocrm_contact_id=1000,
                        telegram_username="chat10"
                    ),
                    ChatMapping(
                        account_id=account_id,
                        telegram_chat_id=20,
                        amocrm_contact_id=2000,
                        telegram_username="chat20"
                    )
                ])
                await session.commit()

                processing = MessageOutbox(
                    idempotency_key="processing-1",
                    account_id=account_id,
                    chat_id=10,
                    payload={"text": "processing"},
                    status="processing",
                    attempts=0
                )
                queued_blocked = MessageOutbox(
                    idempotency_key="queued-1",
                    account_id=account_id,
                    chat_id=10,
                    payload={"text": "queued"},
                    status="queued",
                    attempts=0
                )
                queued_allowed = MessageOutbox(
                    idempotency_key="queued-2",
                    account_id=account_id,
                    chat_id=20,
                    payload={"text": "queued"},
                    status="queued",
                    attempts=0
                )
                session.add_all([processing, queued_blocked, queued_allowed])
                await session.commit()

                next_outbox = await acquire_next_outbox(session)
                self.assertIsNotNone(next_outbox)
                self.assertEqual(next_outbox.chat_id, 20)

        asyncio.run(_run())

    def test_outbox_non_retryable(self):
        async def _run():
            account_id = await ensure_default_account()
            async with SessionLocal() as session:
                await session.execute(MessageDeliveryAttempt.__table__.delete())
                await session.execute(MessageOutbox.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

                session.add(ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=30,
                    amocrm_contact_id=3000,
                    telegram_username="chat30"
                ))
                await session.commit()

                outbox = MessageOutbox(
                    idempotency_key="dead-1",
                    account_id=account_id,
                    chat_id=30,
                    payload={"text": "fail"},
                    status="queued",
                    attempts=0
                )
                session.add(outbox)
                await session.commit()
                await session.refresh(outbox)

                await mark_outbox_non_retryable(session, outbox, "user_not_found")
                result = await session.execute(
                    select(MessageOutbox).filter_by(id=outbox.id)
                )
                updated = result.scalars().first()
                self.assertEqual(updated.status, "dead")
                self.assertEqual(updated.attempts, 1)
                result = await session.execute(
                    select(MessageDeliveryAttempt).filter_by(outbox_id=outbox.id)
                )
                attempts = result.scalars().all()
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0].status, "dead")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
