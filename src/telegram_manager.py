"""
Telegram multi-account manager.
"""

import asyncio
from typing import Dict, List, Optional

from sqlalchemy import select

from src.database import SessionLocal, TelegramAccount, ensure_default_account
from src.logger import logger
from src.telegram_client import MTProtoClient


class TelegramClientManager:
    def __init__(self) -> None:
        self._clients: Dict[int, MTProtoClient] = {}
        self._accounts: Dict[int, TelegramAccount] = {}
        self._account_order: List[int] = []
        self._rr_index = 0
        self._lock = asyncio.Lock()
        self._bridge = None

    async def set_bridge(self, bridge):
        """
        Установка bridge для обработки входящих сообщений.

        Fix #123: Use lock to prevent race condition with concurrent client additions.
        """
        async with self._lock:
            self._bridge = bridge
            # Обновляем bridge во всех существующих клиентах
            for client in self._clients.values():
                client.bridge = bridge
            logger.info("✅ Bridge установлен в TelegramClientManager и во всех клиентах")

    async def refresh_accounts(self, active_only: bool = True) -> List[TelegramAccount]:
        async with SessionLocal() as session:
            stmt = select(TelegramAccount)
            if active_only:
                stmt = stmt.filter_by(is_active=True)
            stmt = stmt.order_by(TelegramAccount.id.asc())
            result = await session.execute(stmt)
            accounts = result.scalars().all()

        self._accounts = {account.id: account for account in accounts}
        self._account_order = [account.id for account in accounts]
        if self._rr_index >= len(self._account_order):
            self._rr_index = 0
        return accounts

    async def get_account(self, account_id: int) -> Optional[TelegramAccount]:
        if account_id not in self._accounts:
            await self.refresh_accounts(active_only=False)
        return self._accounts.get(account_id)

    async def ensure_default_account(self) -> Optional[int]:
        return await ensure_default_account()

    async def get_default_account_id(self) -> Optional[int]:
        default_id = await self.ensure_default_account()
        if default_id and default_id not in self._accounts:
            await self.refresh_accounts(active_only=False)
        if self._account_order:
            return self._account_order[0]
        return default_id

    async def select_account_id(self) -> Optional[int]:
        async with self._lock:
            if not self._account_order:
                await self.refresh_accounts(active_only=True)
            if not self._account_order:
                return None
            account_id = self._account_order[self._rr_index % len(self._account_order)]
            self._rr_index = (self._rr_index + 1) % len(self._account_order)
            return account_id

    async def get_client(self, account_id: int) -> MTProtoClient:
        # Double-checked locking to prevent duplicate client creation
        # First check without lock (fast path)
        if account_id in self._clients:
            return self._clients[account_id]

        # Acquire lock for client creation
        async with self._lock:
            # Double-check after acquiring lock (TOCTOU protection)
            if account_id in self._clients:
                return self._clients[account_id]

            account = await self.get_account(account_id)
            if not account:
                raise ValueError(f"telegram account {account_id} not found")

            client = MTProtoClient(
                account_id=account.id,
                phone_number=account.phone_number,
                session_string=account.session_string,
                bridge=self._bridge
            )

            # Wrap client.start() in try-except to prevent state corruption
            # If start() fails, the client object is left in memory but not registered
            # Next call would create a new client and fail again
            try:
                await client.start()
            except Exception as exc:
                # Rollback: clean up client resources to prevent memory leak
                try:
                    await client.stop()
                except Exception:
                    pass  # Ignore errors during cleanup
                logger.error(
                    f"❌ Не удалось запустить MTProto клиент для account_id={account_id}: {exc}"
                )
                # Re-raise to propagate error to caller
                raise

            self._clients[account_id] = client
            logger.info("✅ MTProto клиент запущен для account_id=%s", account_id)
            return client

    async def start_all(self) -> List[MTProtoClient]:
        await self.ensure_default_account()
        accounts = await self.refresh_accounts(active_only=True)
        clients: List[MTProtoClient] = []
        for account in accounts:
            client = await self.get_client(account.id)
            clients.append(client)
        return clients

    async def stop_all(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.stop()
            except Exception as exc:
                logger.warning("⚠️ Ошибка остановки клиента %s: %s", client.account_id, exc)

    async def stop_client(self, account_id: int) -> None:
        client = self._clients.pop(account_id, None)
        if not client:
            return
        try:
            await client.stop()
        except Exception as exc:
            logger.warning("⚠️ Ошибка остановки клиента %s: %s", account_id, exc)

    async def get_status(self) -> List[dict]:
        accounts = await self.refresh_accounts(active_only=False)
        statuses = []
        for account in accounts:
            client = self._clients.get(account.id)
            if client:
                authorized = await client.is_authorized()
                user = None
                if authorized and client.me:
                    user = {
                        "id": client.me.id,
                        "username": client.me.username,
                        "phone": client.me.phone,
                    }
                status = {
                    "account_id": account.id,
                    "phone_number": account.phone_number,
                    "label": account.label or account.phone_number,
                    "is_active": account.is_active,
                    "connected": client.client.is_connected(),
                    "authorized": authorized,
                    "user": user,
                    "session": client.get_session_info(),
                    "anti_spam": client.anti_spam.get_stats(),
                }
            else:
                status = {
                    "account_id": account.id,
                    "phone_number": account.phone_number,
                    "label": account.label or account.phone_number,
                    "is_active": account.is_active,
                    "connected": False,
                    "authorized": False,
                    "user": None,
                    "session": {},
                    "anti_spam": {},
                }
            statuses.append(status)
        return statuses

    def apply_antispam_limits(
        self,
        max_messages_per_hour: int,
        max_new_chats_per_day: int,
        min_delay_between_messages: int
    ) -> None:
        for client in self._clients.values():
            client.anti_spam.update_limits(
                max_messages_per_hour,
                max_new_chats_per_day,
                min_delay_between_messages
            )

    def get_run_tasks(self) -> List[asyncio.Task]:
        tasks = []
        for client in self._clients.values():
            tasks.append(asyncio.create_task(client.run()))
        return tasks
