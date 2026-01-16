import os
import asyncio
import unittest

from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_telegram_session.db")

from src.database import init_db, SessionLocal, TelegramSession


class TelegramSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_path = "test_telegram_session.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        async def _setup():
            await init_db()
            async with SessionLocal() as session:
                await session.execute(TelegramSession.__table__.delete())
                await session.commit()

        asyncio.run(_setup())

    def test_telegram_session_insert(self):
        async def _run():
            async with SessionLocal() as session:
                record = TelegramSession(
                    phone="+10000000000",
                    session_string="test-session",
                )
                session.add(record)
                await session.commit()
                await session.refresh(record)

                result = await session.execute(
                    select(TelegramSession).filter_by(phone="+10000000000")
                )
                fetched = result.scalars().first()
                self.assertIsNotNone(fetched)
                self.assertEqual(fetched.session_string, "test-session")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
