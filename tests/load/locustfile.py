import os
from locust import HttpUser, task, between


def _env_int(name, default=None):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


class UiUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.auth = (
            os.getenv("UI_LOAD_USER", "admin"),
            os.getenv("UI_LOAD_PASS", "pass")
        )
        self.chat_id = _env_int("UI_LOAD_CHAT_ID", 42)
        self.account_id = _env_int("UI_LOAD_ACCOUNT_ID")

    def _chat_params(self):
        params = []
        if self.account_id:
            params.append(f"account_id={self.account_id}")
        return ("?" + "&".join(params)) if params else ""

    def _message_params(self):
        params = [f"chat_id={self.chat_id}", "limit=50"]
        if self.account_id:
            params.append(f"account_id={self.account_id}")
        return "?" + "&".join(params)

    @task(3)
    def ui_status(self):
        self.client.get("/api/ui/status", auth=self.auth, name="/api/ui/status")

    @task(4)
    def ui_chats(self):
        params = ["limit=50"]
        if self.account_id:
            params.append(f"account_id={self.account_id}")
        self.client.get(
            f"/api/ui/chats?{'&'.join(params)}",
            auth=self.auth,
            name="/api/ui/chats"
        )

    @task(3)
    def ui_messages(self):
        if not self.chat_id:
            return
        self.client.get(
            f"/api/ui/messages{self._message_params()}",
            auth=self.auth,
            name="/api/ui/messages"
        )

    @task(2)
    def ui_templates(self):
        self.client.get("/api/ui/templates", auth=self.auth, name="/api/ui/templates")

    @task(2)
    def ui_tags(self):
        self.client.get("/api/ui/tags", auth=self.auth, name="/api/ui/tags")

    @task(2)
    def ui_events(self):
        self.client.get("/api/ui/events?limit=30", auth=self.auth, name="/api/ui/events")

    @task(1)
    def ui_send(self):
        if not self.chat_id:
            return
        payload = {"chat_id": self.chat_id, "message": "Load test ping"}
        if self.account_id:
            payload["account_id"] = self.account_id
        self.client.post("/api/ui/send", json=payload, auth=self.auth, name="/api/ui/send")
