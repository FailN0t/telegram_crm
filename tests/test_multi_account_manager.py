import os
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

os.environ.setdefault("TELEGRAM_API_ID", "123456")
os.environ.setdefault("TELEGRAM_API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("TELEGRAM_PHONE", "+10000000000")
os.environ.setdefault("API_SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_multi_account.db")

from src.database import init_db, SessionLocal, TelegramAccount
from src.telegram_manager import TelegramClientManager


class MultiAccountManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_path = "test_multi_account.db"
        if os.path.exists(db_path):
            os.remove(db_path)

        async def _setup():
            await init_db()
            async with SessionLocal() as session:
                await session.execute(TelegramAccount.__table__.delete())
                session.add_all([
                    TelegramAccount(phone_number="+10000000001", label="A1", is_active=True),
                    TelegramAccount(phone_number="+10000000002", label="A2", is_active=True),
                ])
                await session.commit()

        asyncio.run(_setup())

    def test_round_robin_selection(self):
        async def _run():
            manager = TelegramClientManager()
            await manager.refresh_accounts(active_only=True)
            first = await manager.select_account_id()
            second = await manager.select_account_id()
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertNotEqual(first, second)

        asyncio.run(_run())

    def test_get_client_returns_per_account_instances(self):
        async def _run():
            manager = TelegramClientManager()
            async with SessionLocal() as session:
                result = await session.execute(select(TelegramAccount).order_by(TelegramAccount.id.asc()))
                accounts = result.scalars().all()

            with patch("src.telegram_manager.MTProtoClient.start", new=AsyncMock()):
                client_one = await manager.get_client(accounts[0].id)
                client_two = await manager.get_client(accounts[1].id)

            self.assertNotEqual(client_one.account_id, client_two.account_id)
            self.assertIsNot(client_one, client_two)
            self.assertIsNot(client_one.anti_spam, client_two.anti_spam)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
