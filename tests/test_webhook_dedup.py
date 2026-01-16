import os
import asyncio
import unittest

os.environ.setdefault("TELEGRAM_API_ID", "123456")
os.environ.setdefault("TELEGRAM_API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("TELEGRAM_PHONE", "+10000000000")
os.environ.setdefault("API_SECRET_KEY", "test-secret")
os.environ.setdefault("AMOCRM_DOMAIN", "demo.amocrm.ru")
os.environ.setdefault("AMOCRM_CLIENT_ID", "demo_client_id")
os.environ.setdefault("AMOCRM_CLIENT_SECRET", "demo_client_secret")
os.environ.setdefault("AMOCRM_REDIRECT_URI", "http://localhost/oauth")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_webhook.db")

from fastapi.testclient import TestClient

from src import api_server
from sqlalchemy import select

from src.database import init_db, ensure_default_account, SessionLocal, ChatMapping, MessageInbox, MessageOutbox


class DummyBridge:
    def __init__(self):
        self.amocrm = None
        self.telegram = DummyManager()


class DummyManager:
    DEFAULT_ACCOUNT_ID = 1

    async def get_default_account_id(self):
        return self.DEFAULT_ACCOUNT_ID


class WebhookDedupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_path = "test_webhook.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        async def _setup():
            await init_db()
            async with SessionLocal() as session:
                await session.execute(MessageInbox.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                account_id = await ensure_default_account()
                DummyManager.DEFAULT_ACCOUNT_ID = account_id
                session.add(ChatMapping(
                    account_id=account_id,
                    telegram_chat_id=0,
                    amocrm_contact_id=0,
                    telegram_username="placeholder"
                ))
                await session.commit()

        asyncio.run(_setup())
        api_server.set_bridge(DummyBridge())
        cls.client = TestClient(api_server.app)

    def test_amocrm_webhook_dedup(self):
        payload = {
            "tasks": {
                "add": [
                    {"id": 101}
                ]
            }
        }
        first = self.client.post("/api/webhook/amocrm", json=payload)
        self.assertEqual(first.status_code, 200)
        data = first.json()
        self.assertEqual(data["processed"], 1)
        self.assertTrue(data["results"][0]["queued"])

        second = self.client.post("/api/webhook/amocrm", json=payload)
        self.assertEqual(second.status_code, 200)
        data2 = second.json()
        self.assertEqual(data2["processed"], 0)
        self.assertEqual(data2["status"], "duplicate")

        async def _check_outbox():
            async with SessionLocal() as session:
                result = await session.execute(
                    select(MessageOutbox).filter_by(idempotency_key="amocrm_task:101")
                )
                entry = result.scalars().first()
                self.assertIsNotNone(entry)

        asyncio.run(_check_outbox())


if __name__ == "__main__":
    unittest.main()
