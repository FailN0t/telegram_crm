import os
import asyncio
import unittest
from datetime import datetime
from sqlalchemy import select
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_API_ID", "123456")
os.environ.setdefault("TELEGRAM_API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("TELEGRAM_PHONE", "+10000000000")
os.environ.setdefault("API_SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ui.db")

from fastapi.testclient import TestClient

from src import api_server
from src.database import (
    init_db,
    SessionLocal,
    UiMessageHistory,
    UiEventLog,
    Operator,
    MessageOutbox
)


class DummyAntiSpam:
    def get_stats(self):
        return {
            "messages_sent_this_hour": 1,
            "max_messages_per_hour": 50,
            "new_chats_today": 1,
            "max_new_chats_per_day": 20,
            "min_delay_between_messages": 5,
            "hour_started_at": "2026-01-01T00:00:00Z",
            "day_started_at": "2026-01-01T00:00:00Z",
            "last_message_at": None,
            "current_time": "2026-01-01T00:00:00Z"
        }


class DummyUser:
    def __init__(self, user_id, username="tester"):
        self.id = user_id
        self.username = username
        self.first_name = "Test"
        self.last_name = "User"
        self.phone = "+10000000000"


class DummyTelegram:
    def __init__(self):
        self.account_id = 1
        self.client = SimpleNamespace(is_connected=lambda: True)
        self.me = DummyUser(1, "me")
        self.anti_spam = DummyAntiSpam()
        self.send_count = 0
        self._messages = [
            {
                "account_id": 1,
                "id": 1,
                "direction": "inbound",
                "chat_id": 42,
                "username": "demo",
                "display_name": "Demo User",
                "text": "hello",
                "timestamp": "2026-01-01T10:00:00Z"
            }
        ]
        self._chats = [
            {
                "account_id": 1,
                "chat_id": 42,
                "username": "demo",
                "display_name": "Demo User",
                "last_message": "hello",
                "last_timestamp": "2026-01-01T10:00:00Z",
                "unread_count": 1
            }
        ]

    async def is_authorized(self):
        return True

    def get_session_info(self):
        return {"name": "test", "path": "test.session", "exists": True}

    async def request_code(self, phone=None):
        return True, "code_sent"

    async def submit_code(self, code, phone=None):
        return True, "authorized"

    async def submit_password(self, password):
        return True, "authorized"

    async def logout(self):
        return True, "logged_out"

    async def get_chats(self, limit=80):
        return self._chats

    async def mark_chat_read(self, chat_id):
        return None

    async def get_recent_messages(self, limit=50, chat_id=None):
        if chat_id is None:
            return self._messages
        return [msg for msg in self._messages if msg["chat_id"] == chat_id]

    async def get_chat_details(self, chat_id):
        return {
            "account_id": 1,
            "chat_id": chat_id,
            "username": "demo",
            "display_name": "Demo User",
            "phone": "+10000000000"
        }

    async def get_chat_history_stats(self, chat_id):
        return {
            "messages_total": 1,
            "inbound_count": 1,
            "outbound_count": 0,
            "last_inbound_at": "2026-01-01T10:00:00Z",
            "last_outbound_at": None
        }

    async def find_user_by_id(self, chat_id):
        return DummyUser(chat_id)

    async def find_user_by_username(self, username):
        return DummyUser(42, username)

    async def find_user_by_phone(self, phone):
        return DummyUser(43, "phone")

    async def send_message_to_user(self, user, message, operator_id=None):
        self.send_count += 1
        return True, "Успешно отправлено"

    def _format_chat_name(self, username, first_name, last_name, chat_id):
        display = " ".join(part for part in [first_name, last_name] if part)
        if display:
            return display
        if username:
            return f"@{username}"
        return str(chat_id)


class DummyBridge:
    def __init__(self):
        self.telegram = DummyManager()
        self.amocrm = None


class DummyManager:
    def __init__(self):
        self._client = DummyTelegram()

    @property
    def send_count(self):
        return self._client.send_count

    @send_count.setter
    def send_count(self, value):
        self._client.send_count = value

    async def get_status(self):
        user = {
            "id": self._client.me.id,
            "username": self._client.me.username,
            "phone": self._client.me.phone,
        }
        return [
            {
                "account_id": self._client.account_id,
                "phone_number": self._client.me.phone,
                "label": "Test Account",
                "is_active": True,
                "connected": True,
                "authorized": True,
                "user": user,
                "session": self._client.get_session_info(),
                "anti_spam": self._client.anti_spam.get_stats(),
            }
        ]

    async def get_default_account_id(self):
        return self._client.account_id

    async def select_account_id(self):
        return self._client.account_id

    async def get_client(self, account_id):
        return self._client


class UiApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_path = "test_ui.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        async def _setup():
            await init_db()
            async with SessionLocal() as session:
                await session.execute(UiMessageHistory.__table__.delete())
                await session.execute(UiEventLog.__table__.delete())
                session.add(UiMessageHistory(
                    account_id=1,
                    chat_id=42,
                    direction="inbound",
                    message_text="hello",
                    message_type="text",
                    username="demo",
                    display_name="Demo User",
                    status="received"
                ))
                await session.commit()

                result = await session.execute(
                    select(UiMessageHistory).filter_by(chat_id=42)
                )
                assert result.scalars().first()

        asyncio.run(_setup())
        api_server.set_bridge(DummyBridge())
        cls.client = TestClient(api_server.app)

    def test_ui_status(self):
        resp = self.client.get("/api/ui/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["connected"])
        self.assertTrue(data["authorized"])
        self.assertIn("session", data)
        self.assertIn("anti_spam", data)

    def test_ui_accounts(self):
        resp = self.client.get("/api/ui/accounts")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("accounts", data)
        self.assertTrue(len(data["accounts"]) >= 1)

    def test_health_endpoints(self):
        live = self.client.get("/live")
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json()["status"], "alive")

        startup = self.client.get("/startup")
        self.assertEqual(startup.status_code, 200)
        self.assertEqual(startup.json()["status"], "started")

        ready = self.client.get("/ready")
        self.assertEqual(ready.status_code, 200)
        data = ready.json()
        self.assertIn("status", data)
        self.assertTrue(data["database_connected"])
        self.assertTrue(data["telegram_connected"])

    def test_ui_chats_and_messages(self):
        chats = self.client.get("/api/ui/chats").json()
        self.assertEqual(len(chats["chats"]), 1)

        messages = self.client.get("/api/ui/messages?chat_id=42").json()
        self.assertEqual(len(messages["messages"]), 1)

    def test_ui_send_message(self):
        resp = self.client.post("/api/ui/send", json={"chat_id": 42, "message": "hi"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])

    def test_ui_send_message_idempotent(self):
        key = "idempotent-ui-1"
        api_server.bridge.telegram.send_count = 0
        resp = self.client.post(
            "/api/ui/send",
            json={"chat_id": 42, "message": "hello", "idempotency_key": key}
        )
        self.assertEqual(resp.status_code, 200)
        resp2 = self.client.post(
            "/api/ui/send",
            json={"chat_id": 42, "message": "hello", "idempotency_key": key}
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(api_server.bridge.telegram.send_count, 1)

    def test_ui_send_message_queued(self):
        api_server.settings.OUTBOX_PROCESS_INLINE = False
        api_server.bridge.telegram.send_count = 0
        resp = self.client.post("/api/ui/send", json={"chat_id": 42, "message": "queued"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "queued")
        self.assertEqual(api_server.bridge.telegram.send_count, 0)
        api_server.settings.OUTBOX_PROCESS_INLINE = True

    def test_ui_send_message_missing_target(self):
        resp = self.client.post("/api/ui/send", json={"message": "hi"})
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["success"])

    def test_ui_operators_list(self):
        async def _setup():
            async with SessionLocal() as session:
                operator = Operator(
                    username="alice",
                    display_name="Alice",
                    email="alice@example.com",
                    hourly_limit=12,
                    daily_limit=34
                )
                session.add(operator)
                await session.commit()
                await session.refresh(operator)

                outbox = MessageOutbox(
                    idempotency_key="op-1",
                    account_id=1,
                    operator_id=operator.id,
                    chat_id=101,
                    payload={"text": "hi"},
                    status="sent",
                    created_at=datetime.utcnow()
                )
                session.add(outbox)
                await session.commit()

        asyncio.run(_setup())
        resp = self.client.get("/api/ui/operators")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(any(item["username"] == "alice" for item in data["operators"]))

    def test_ui_operator_update_requires_admin(self):
        async def _setup():
            async with SessionLocal() as session:
                operator = Operator(
                    username="bob",
                    display_name="Bob",
                    email="bob@example.com",
                    hourly_limit=10,
                    daily_limit=20
                )
                session.add(operator)
                await session.commit()
                await session.refresh(operator)
                return operator.id

        operator_id = asyncio.run(_setup())
        resp = self.client.patch(
            f"/api/ui/operators/{operator_id}",
            json={"hourly_limit": 25, "daily_limit": 50}
        )
        self.assertEqual(resp.status_code, 403)

        api_server.settings.UI_BASIC_AUTH_ENABLED = True
        api_server.settings.UI_BASIC_AUTH_USERS = "admin:pass:admin"
        api_server._ui_users_cache["raw"] = None
        resp = self.client.patch(
            f"/api/ui/operators/{operator_id}",
            json={"hourly_limit": 25, "daily_limit": 50},
            auth=("admin", "pass")
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["operator"]["hourly_limit"], 25)
        self.assertEqual(data["operator"]["daily_limit"], 50)

        api_server.settings.UI_BASIC_AUTH_ENABLED = False
        api_server.settings.UI_BASIC_AUTH_USERS = None
        api_server._ui_users_cache["raw"] = None

    def test_chat_profile_crud(self):
        update = self.client.post(
            "/api/ui/chat/42/profile",
            json={"tags": "vip, lead", "notes": "first contact"}
        )
        self.assertEqual(update.status_code, 200)
        data = update.json()
        self.assertTrue(data["success"])
        details = self.client.get("/api/ui/chat/42").json()
        self.assertEqual(details["profile"]["tags"], "vip, lead")
        self.assertEqual(details["profile"]["notes"], "first contact")

    def test_ui_events(self):
        self.client.post("/api/ui/send", json={"chat_id": 42, "message": "hi"})
        events = self.client.get("/api/ui/events").json()["events"]
        self.assertTrue(any(event["message"] == "send_success" for event in events))

    def test_ui_basic_auth(self):
        api_server.settings.UI_BASIC_AUTH_ENABLED = True
        api_server.settings.UI_BASIC_AUTH_USERS = "admin:pass:admin"
        api_server._ui_users_cache["raw"] = None

        unauthorized = self.client.get("/api/ui/status")
        self.assertEqual(unauthorized.status_code, 401)

        authorized = self.client.get(
            "/api/ui/status",
            auth=("admin", "pass")
        )
        self.assertEqual(authorized.status_code, 200)

        events = self.client.get(
            "/api/ui/events",
            auth=("admin", "pass")
        ).json()["events"]
        self.assertTrue(any(event["message"] == "ui_auth_failed" for event in events))
        self.assertTrue(any(event["message"] == "ui_auth_ok" for event in events))

        api_server.settings.UI_BASIC_AUTH_ENABLED = False
        api_server.settings.UI_BASIC_AUTH_USERS = None
        api_server._ui_users_cache["raw"] = None


if __name__ == "__main__":
    unittest.main()
