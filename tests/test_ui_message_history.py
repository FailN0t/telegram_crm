import os
import asyncio
import unittest

from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ui_history.db")

from src.database import init_db, ensure_default_account, SessionLocal, ChatMapping, UiMessageHistory


class UiMessageHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_path = "test_ui_history.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        asyncio.run(init_db())

    def test_ui_message_history_insert(self):
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
                entry = UiMessageHistory(
                    account_id=account_id,
                    chat_id=123,
                    direction="outbound",
                    message_text="hello",
                    message_type="text",
                    username="demo",
                    display_name="Demo User",
                    status="sent",
                    media_url="http://localhost/media/1.png",
                    media_name="1.png",
                    media_mime="image/png",
                    media_size=128
                )
                session.add(entry)
                await session.commit()
                await session.refresh(entry)

                result = await session.execute(
                    select(UiMessageHistory).filter_by(id=entry.id)
                )
                fetched = result.scalars().first()
                self.assertIsNotNone(fetched)
                self.assertEqual(fetched.chat_id, 123)
                self.assertEqual(fetched.status, "sent")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
