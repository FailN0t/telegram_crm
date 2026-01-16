"""
Anti-Spam менеджер для предотвращения блокировки
"""

import asyncio
from datetime import datetime, timedelta
from typing import Tuple

from src.config import settings
from src.logger import logger
from src.redis_client import get_redis


class AntiSpamManager:
    """
    Менеджер для контроля лимитов отправки сообщений
    Предотвращает блокировку аккаунта Telegram
    """
    
    def __init__(self):
        # Счетчики
        self.message_count = 0
        self.hour_start = datetime.now()
        self.daily_new_chats = 0
        self.day_start = datetime.now()
        self.sent_to_today = set()
        
        # Лимиты из конфигурации
        self.MAX_MESSAGES_PER_HOUR = settings.MAX_MESSAGES_PER_HOUR
        self.MAX_NEW_CHATS_PER_DAY = settings.MAX_NEW_CHATS_PER_DAY
        self.MIN_DELAY_BETWEEN_MESSAGES = settings.MIN_DELAY_BETWEEN_MESSAGES
        
        self.last_message_time = None
        self._lock = asyncio.Lock()
        
        logger.info(
            f"📊 Anti-Spam инициализирован: "
            f"{self.MAX_MESSAGES_PER_HOUR} msg/hour, "
            f"{self.MAX_NEW_CHATS_PER_DAY} new chats/day, "
            f"{self.MIN_DELAY_BETWEEN_MESSAGES}s delay"
        )

    async def initialize(self) -> None:
        redis = await get_redis()
        if not redis:
            return

        now = datetime.now()
        hour_key = self._hour_key(now)
        day_key = self._day_key(now)
        last_key = self._last_message_key()
        try:
            hour_value = await redis.get(hour_key)
            day_value = await redis.get(day_key)
            last_value = await redis.get(last_key)
        except Exception as exc:
            logger.warning(f"⚠️ Redis недоступен для anti-spam: {exc}")
            return

        self.message_count = int(hour_value or 0)
        self.daily_new_chats = int(day_value or 0)
        self.hour_start = now.replace(minute=0, second=0, microsecond=0)
        self.day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if last_value:
            try:
                self.last_message_time = datetime.fromtimestamp(float(last_value))
            except ValueError:
                self.last_message_time = None

    def _hour_key(self, now: datetime) -> str:
        return f"antispam:hour:{now.strftime('%Y%m%d%H')}"

    def _day_key(self, now: datetime) -> str:
        return f"antispam:day:{now.strftime('%Y%m%d')}:new_chats"

    def _day_users_key(self, now: datetime) -> str:
        return f"antispam:day:{now.strftime('%Y%m%d')}:users"

    def _last_message_key(self) -> str:
        return "antispam:last_message_at"

    async def try_register_send(self, user_id: int, is_new_chat: bool = False) -> Tuple[bool, str]:
        """
        Проверяет лимиты и регистрирует отправку одним атомарным шагом
        
        Args:
            user_id: ID пользователя Telegram
            is_new_chat: Является ли это первым сообщением пользователю
            
        Returns:
            (bool, str): (можно ли отправить, причина если нельзя)
        """
        async with self._lock:
            now = datetime.now()

            # Проверка времени отправки (не ночью)
            if now.hour < 9 or now.hour > 21:
                return False, f"⏰ Неподходящее время ({now.hour}:00). Отправляйте с 9:00 до 21:00"

            redis = await get_redis()
            if redis:
                return await self._try_register_with_redis(redis, now, user_id, is_new_chat)

            return self._try_register_in_memory(now, user_id, is_new_chat)

    async def _try_register_with_redis(
        self,
        redis,
        now: datetime,
        user_id: int,
        is_new_chat: bool
    ) -> Tuple[bool, str]:
        hour_key = self._hour_key(now)
        day_key = self._day_key(now)
        users_key = self._day_users_key(now)
        last_key = self._last_message_key()

        try:
            hour_value = await redis.get(hour_key)
            day_value = await redis.get(day_key)
            last_value = await redis.get(last_key)
            already_contacted = await redis.sismember(users_key, user_id)
        except Exception as exc:
            logger.warning(f"⚠️ Redis недоступен для anti-spam: {exc}")
            return self._try_register_in_memory(now, user_id, is_new_chat)

        message_count = int(hour_value or 0)
        daily_new_chats = int(day_value or 0)
        if already_contacted:
            is_new_chat = False

        if message_count >= self.MAX_MESSAGES_PER_HOUR:
            return False, (
                f"⚠️ Превышен лимит сообщений в час "
                f"({message_count}/{self.MAX_MESSAGES_PER_HOUR})"
            )

        if is_new_chat and daily_new_chats >= self.MAX_NEW_CHATS_PER_DAY:
            return False, (
                f"⚠️ Превышен лимит новых чатов в день "
                f"({daily_new_chats}/{self.MAX_NEW_CHATS_PER_DAY})"
            )

        if last_value:
            try:
                last_dt = datetime.fromtimestamp(float(last_value))
                time_since_last = (now - last_dt).total_seconds()
                if time_since_last < self.MIN_DELAY_BETWEEN_MESSAGES:
                    wait_time = self.MIN_DELAY_BETWEEN_MESSAGES - time_since_last
                    return False, f"⏳ Подождите {wait_time:.1f}с перед следующим сообщением"
            except ValueError:
                pass

        pipeline = redis.pipeline(transaction=True)
        pipeline.incr(hour_key)
        pipeline.expire(hour_key, 2 * 60 * 60)
        if is_new_chat:
            pipeline.incr(day_key)
        pipeline.expire(day_key, 2 * 24 * 60 * 60)
        pipeline.sadd(users_key, user_id)
        pipeline.expire(users_key, 2 * 24 * 60 * 60)
        pipeline.set(last_key, str(now.timestamp()))
        pipeline.expire(last_key, max(int(self.MIN_DELAY_BETWEEN_MESSAGES * 2), 60))
        await pipeline.execute()

        self.message_count = message_count + 1
        self.daily_new_chats = daily_new_chats + (1 if is_new_chat else 0)
        self.last_message_time = now
        self.hour_start = now.replace(minute=0, second=0, microsecond=0)
        self.day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        logger.info(
            f"📊 Статистика: {self.message_count}/{self.MAX_MESSAGES_PER_HOUR} сообщений/час, "
            f"{self.daily_new_chats}/{self.MAX_NEW_CHATS_PER_DAY} новых чатов/день"
        )
        return True, "✅ OK"

    def _try_register_in_memory(
        self,
        now: datetime,
        user_id: int,
        is_new_chat: bool
    ) -> Tuple[bool, str]:
        if (now - self.hour_start) > timedelta(hours=1):
            logger.info(
                f"🔄 Сброс почасового счетчика. "
                f"Отправлено за час: {self.message_count}"
            )
            self.message_count = 0
            self.hour_start = now

        if (now - self.day_start) > timedelta(days=1):
            logger.info(
                f"🔄 Сброс дневного счетчика. "
                f"Новых чатов за день: {self.daily_new_chats}"
            )
            self.daily_new_chats = 0
            self.day_start = now
            self.sent_to_today.clear()

        if self.message_count >= self.MAX_MESSAGES_PER_HOUR:
            return False, (
                f"⚠️ Превышен лимит сообщений в час "
                f"({self.message_count}/{self.MAX_MESSAGES_PER_HOUR})"
            )

        if user_id in self.sent_to_today:
            is_new_chat = False

        if is_new_chat and self.daily_new_chats >= self.MAX_NEW_CHATS_PER_DAY:
            return False, (
                f"⚠️ Превышен лимит новых чатов в день "
                f"({self.daily_new_chats}/{self.MAX_NEW_CHATS_PER_DAY})"
            )

        if self.last_message_time:
            time_since_last = (now - self.last_message_time).total_seconds()
            if time_since_last < self.MIN_DELAY_BETWEEN_MESSAGES:
                wait_time = self.MIN_DELAY_BETWEEN_MESSAGES - time_since_last
                return False, f"⏳ Подождите {wait_time:.1f}с перед следующим сообщением"

        self.message_count += 1
        self.last_message_time = now
        self.sent_to_today.add(user_id)
        if is_new_chat:
            self.daily_new_chats += 1

        logger.info(
            f"📊 Статистика: {self.message_count}/{self.MAX_MESSAGES_PER_HOUR} сообщений/час, "
            f"{self.daily_new_chats}/{self.MAX_NEW_CHATS_PER_DAY} новых чатов/день"
        )
        return True, "✅ OK"
    
    def get_stats(self) -> dict:
        """Получить текущую статистику"""
        now = datetime.now()
        
        return {
            "messages_sent_this_hour": self.message_count,
            "max_messages_per_hour": self.MAX_MESSAGES_PER_HOUR,
            "new_chats_today": self.daily_new_chats,
            "max_new_chats_per_day": self.MAX_NEW_CHATS_PER_DAY,
            "min_delay_between_messages": self.MIN_DELAY_BETWEEN_MESSAGES,
            "hour_started_at": self.hour_start.isoformat(),
            "day_started_at": self.day_start.isoformat(),
            "last_message_at": self.last_message_time.isoformat() if self.last_message_time else None,
            "current_time": now.isoformat(),
        }
