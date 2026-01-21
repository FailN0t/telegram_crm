"""
Anti-Spam менеджер для предотвращения блокировки
"""

import asyncio
from datetime import datetime, timedelta
from typing import Tuple, Optional

from sqlalchemy import select

from src.config import settings
from src.database import SessionLocal, Operator
from src.logger import logger
from src.redis_client import get_redis


# Lua скрипт для атомарной проверки и инкремента счетчика
# Возвращает: {1, new_value} если успешно, {0, current_value} если лимит превышен
LUA_ATOMIC_CHECK_INCREMENT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = redis.call('GET', key)
if current and tonumber(current) >= limit then
    return {0, tonumber(current)}
end

local new_val = redis.call('INCR', key)
if new_val == 1 then
    redis.call('EXPIRE', key, ttl)
end
return {1, new_val}
"""

# Lua скрипт для атомарной проверки времени последнего сообщения
# Возвращает: {1, timestamp} если можно отправить, {0, timestamp, wait_seconds} если нужно подождать
LUA_ATOMIC_CHECK_DELAY = """
local key = KEYS[1]
local min_delay = tonumber(ARGV[1])
local current_timestamp = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])

local last_timestamp = redis.call('GET', key)
if last_timestamp then
    local time_since_last = current_timestamp - tonumber(last_timestamp)
    if time_since_last < min_delay then
        local wait_time = min_delay - time_since_last
        return {0, tonumber(last_timestamp), wait_time}
    end
end

redis.call('SET', key, tostring(current_timestamp))
redis.call('EXPIRE', key, ttl)
return {1, current_timestamp}
"""

# Lua скрипт для безопасного декремента (не уходит в минус, игнорирует несуществующие ключи)
# Возвращает: новое значение или 0 если ключ не существует
LUA_SAFE_DECREMENT = """
local key = KEYS[1]
local current = redis.call('GET', key)
if not current then
    return 0
end
local current_val = tonumber(current)
if current_val <= 0 then
    return 0
end
return redis.call('DECR', key)
"""


class AntiSpamManager:
    """
    Менеджер для контроля лимитов отправки сообщений
    Предотвращает блокировку аккаунта Telegram
    """

    def __init__(self, account_id: Optional[int] = None):
        self.account_id = account_id or 0
        # Счетчики
        self.message_count = 0
        self.hour_start = datetime.now()
        self.daily_new_chats = 0
        self.day_start = datetime.now()
        self.sent_to_today = set()
        self.operator_hour_counts = {}
        self.operator_day_counts = {}

        # Лимиты из конфигурации
        self.MAX_MESSAGES_PER_HOUR = settings.MAX_MESSAGES_PER_HOUR
        self.MAX_NEW_CHATS_PER_DAY = settings.MAX_NEW_CHATS_PER_DAY
        self.MIN_DELAY_BETWEEN_MESSAGES = settings.MIN_DELAY_BETWEEN_MESSAGES

        self.last_message_time = None
        self._lock = asyncio.Lock()

        # Кеш для скомпилированных Lua скриптов
        self._lua_check_increment_sha: Optional[str] = None
        self._lua_check_delay_sha: Optional[str] = None
        self._lua_safe_decrement_sha: Optional[str] = None

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
        return f"antispam:account:{self.account_id}:hour:{now.strftime('%Y%m%d%H')}"

    def _day_key(self, now: datetime) -> str:
        return f"antispam:account:{self.account_id}:day:{now.strftime('%Y%m%d')}:new_chats"

    def _day_users_key(self, now: datetime) -> str:
        return f"antispam:account:{self.account_id}:day:{now.strftime('%Y%m%d')}:users"

    def _last_message_key(self) -> str:
        return f"antispam:account:{self.account_id}:last_message_at"

    def _operator_hour_key(self, operator_id: int, now: datetime) -> str:
        hour_key = now.strftime("%Y%m%d%H")
        return f"antispam:account:{self.account_id}:operator:{operator_id}:hour:{hour_key}"

    def _operator_day_key(self, operator_id: int, now: datetime) -> str:
        day_key = now.strftime("%Y%m%d")
        return f"antispam:account:{self.account_id}:operator:{operator_id}:day:{day_key}"

    async def _get_operator_limits(self, operator_id: int) -> Optional[Tuple[int, int]]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(Operator).filter_by(id=operator_id)
            )
            operator = result.scalars().first()
        if not operator:
            return None
        hourly_limit = operator.hourly_limit or self.MAX_MESSAGES_PER_HOUR
        daily_limit = operator.daily_limit or self.MAX_MESSAGES_PER_HOUR * 4
        return hourly_limit, daily_limit

    async def _ensure_lua_scripts(self, redis) -> None:
        """Загружает Lua скрипты в Redis если они еще не загружены"""
        if not self._lua_check_increment_sha:
            try:
                self._lua_check_increment_sha = await redis.script_load(LUA_ATOMIC_CHECK_INCREMENT)
                logger.debug("Lua скрипт check_increment загружен")
            except Exception as exc:
                logger.warning(f"Не удалось загрузить Lua скрипт check_increment: {exc}")

        if not self._lua_check_delay_sha:
            try:
                self._lua_check_delay_sha = await redis.script_load(LUA_ATOMIC_CHECK_DELAY)
                logger.debug("Lua скрипт check_delay загружен")
            except Exception as exc:
                logger.warning(f"Не удалось загрузить Lua скрипт check_delay: {exc}")

        if not self._lua_safe_decrement_sha:
            try:
                self._lua_safe_decrement_sha = await redis.script_load(LUA_SAFE_DECREMENT)
                logger.debug("Lua скрипт safe_decrement загружен")
            except Exception as exc:
                logger.warning(f"Не удалось загрузить Lua скрипт safe_decrement: {exc}")

    async def _atomic_check_and_increment(
        self,
        redis,
        key: str,
        limit: int,
        ttl: int
    ) -> Tuple[bool, int]:
        """
        Атомарно проверяет лимит и инкрементирует счетчик

        Args:
            redis: Redis клиент
            key: Ключ счетчика
            limit: Максимальное значение
            ttl: Время жизни ключа в секундах

        Returns:
            (success, current_value): True если успешно, текущее значение
        """
        await self._ensure_lua_scripts(redis)

        try:
            if self._lua_check_increment_sha:
                # Используем EVALSHA для производительности
                result = await redis.evalsha(
                    self._lua_check_increment_sha,
                    1,  # количество ключей
                    key,
                    limit,
                    ttl
                )
            else:
                # Fallback на EVAL если скрипт не загружен
                result = await redis.eval(
                    LUA_ATOMIC_CHECK_INCREMENT,
                    1,
                    key,
                    limit,
                    ttl
                )

            success = bool(result[0])
            current_value = int(result[1])
            return success, current_value

        except Exception as exc:
            logger.error(f"Ошибка при выполнении Lua скрипта check_increment: {exc}")
            raise

    async def _atomic_check_delay(
        self,
        redis,
        key: str,
        min_delay: float,
        current_timestamp: float,
        ttl: int
    ) -> Tuple[bool, float]:
        """
        Атомарно проверяет задержку с последнего сообщения и обновляет timestamp

        Args:
            redis: Redis клиент
            key: Ключ timestamp
            min_delay: Минимальная задержка в секундах
            current_timestamp: Текущий timestamp
            ttl: Время жизни ключа в секундах

        Returns:
            (success, wait_time): True если можно отправить, время ожидания если нет
        """
        await self._ensure_lua_scripts(redis)

        try:
            if self._lua_check_delay_sha:
                result = await redis.evalsha(
                    self._lua_check_delay_sha,
                    1,
                    key,
                    min_delay,
                    current_timestamp,
                    ttl
                )
            else:
                result = await redis.eval(
                    LUA_ATOMIC_CHECK_DELAY,
                    1,
                    key,
                    min_delay,
                    current_timestamp,
                    ttl
                )

            success = bool(result[0])
            if success:
                return True, 0.0
            else:
                wait_time = float(result[2])
                return False, wait_time

        except Exception as exc:
            logger.error(f"Ошибка при выполнении Lua скрипта check_delay: {exc}")
            raise

    async def _safe_decrement(self, redis, key: str) -> int:
        """
        Безопасно декрементирует счетчик (не уходит в минус, игнорирует несуществующие ключи)

        Args:
            redis: Redis клиент
            key: Ключ счетчика

        Returns:
            Новое значение счетчика или 0 если ключ не существует
        """
        await self._ensure_lua_scripts(redis)

        try:
            if self._lua_safe_decrement_sha:
                result = await redis.evalsha(
                    self._lua_safe_decrement_sha,
                    1,  # количество ключей
                    key
                )
            else:
                result = await redis.eval(
                    LUA_SAFE_DECREMENT,
                    1,
                    key
                )

            return int(result)

        except Exception as exc:
            logger.error(f"Ошибка при выполнении Lua скрипта safe_decrement: {exc}")
            # В случае ошибки, fallback на обычный decr
            try:
                current = await redis.get(key)
                if current and int(current) > 0:
                    return await redis.decr(key)
            except Exception:
                pass
            return 0

    async def try_register_send(
        self,
        user_id: int,
        is_new_chat: Optional[bool] = None,
        operator_id: Optional[int] = None,
        skip_quiet_hours: bool = False,
        chat_id: Optional[int] = None,
        account_id: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Проверяет лимиты и регистрирует отправку одним атомарным шагом

        Args:
            user_id: ID пользователя Telegram
            is_new_chat: Является ли это первым сообщением пользователю (если None, определяется автоматически)
            operator_id: ID оператора (если есть)
            skip_quiet_hours: Пропустить проверку тихих часов (для Open Channels)
            chat_id: ID чата для определения is_new_chat (если is_new_chat=None)
            account_id: ID аккаунта для определения is_new_chat (если is_new_chat=None)

        Returns:
            (bool, str): (можно ли отправить, причина если нельзя)
        """
        async with self._lock:
            now = datetime.now()

            # Fix #5: Атомарная проверка is_new_chat внутри lock
            if is_new_chat is None and chat_id is not None and account_id is not None:
                from src.database import SessionLocal, UiChat
                from sqlalchemy import select

                async with SessionLocal() as session:
                    result = await session.execute(
                        select(UiChat).filter_by(
                            chat_id=chat_id,
                            account_id=account_id
                        )
                    )
                    is_new_chat = result.scalars().first() is None

            # Default to False if still not determined
            if is_new_chat is None:
                is_new_chat = False

            # Проверка времени отправки (не ночью)
            # Для Open Channels пропускаем эту проверку
            if not skip_quiet_hours and (now.hour < 9 or now.hour > 21):
                return False, f"⏰ Неподходящее время ({now.hour}:00). Отправляйте с 9:00 до 21:00"

            redis = await get_redis()
            if redis:
                return await self._try_register_with_redis(
                    redis,
                    now,
                    user_id,
                    is_new_chat,
                    operator_id
                )

            operator_limits = None
            if operator_id:
                operator_limits = await self._get_operator_limits(operator_id)
            return self._try_register_in_memory(
                now,
                user_id,
                is_new_chat,
                operator_id,
                operator_limits
            )

    async def _try_register_with_redis(
        self,
        redis,
        now: datetime,
        user_id: int,
        is_new_chat: bool,
        operator_id: Optional[int]
    ) -> Tuple[bool, str]:
        hour_key = self._hour_key(now)
        day_key = self._day_key(now)
        users_key = self._day_users_key(now)
        last_key = self._last_message_key()

        try:
            # Проверяем, контактировали ли мы уже с этим пользователем сегодня
            already_contacted = await redis.sismember(users_key, user_id)
            if already_contacted:
                is_new_chat = False

            # 1. АТОМАРНАЯ проверка задержки между сообщениями
            delay_ok, wait_time = await self._atomic_check_delay(
                redis,
                last_key,
                self.MIN_DELAY_BETWEEN_MESSAGES,
                now.timestamp(),
                max(int(self.MIN_DELAY_BETWEEN_MESSAGES * 2), 60)
            )
            if not delay_ok:
                return False, f"⏳ Подождите {wait_time:.1f}с перед следующим сообщением"

            operator_hour_key = None
            operator_day_key = None
            operator_hour_incremented = False
            operator_day_incremented = False
            if operator_id:
                limits = await self._get_operator_limits(operator_id)
                if limits:
                    operator_hour_limit, operator_day_limit = limits
                    operator_hour_key = self._operator_hour_key(operator_id, now)
                    operator_day_key = self._operator_day_key(operator_id, now)

                    op_hour_ok, op_hour_count = await self._atomic_check_and_increment(
                        redis,
                        operator_hour_key,
                        operator_hour_limit,
                        2 * 60 * 60
                    )
                    if not op_hour_ok:
                        return False, (
                            f"⚠️ Превышен лимит оператора в час "
                            f"({op_hour_count}/{operator_hour_limit})"
                        )
                    operator_hour_incremented = True

                    op_day_ok, op_day_count = await self._atomic_check_and_increment(
                        redis,
                        operator_day_key,
                        operator_day_limit,
                        2 * 24 * 60 * 60
                    )
                    if not op_day_ok:
                        await self._safe_decrement(redis, operator_hour_key)
                        return False, (
                            f"⚠️ Превышен лимит оператора в день "
                            f"({op_day_count}/{operator_day_limit})"
                        )
                    operator_day_incremented = True

            # 2. АТОМАРНАЯ проверка и инкремент почасового лимита
            hour_ok, hour_count = await self._atomic_check_and_increment(
                redis,
                hour_key,
                self.MAX_MESSAGES_PER_HOUR,
                2 * 60 * 60  # TTL = 2 часа
            )
            if not hour_ok:
                if operator_hour_incremented and operator_hour_key:
                    await self._safe_decrement(redis, operator_hour_key)
                if operator_day_incremented and operator_day_key:
                    await self._safe_decrement(redis, operator_day_key)
                return False, (
                    f"⚠️ Превышен лимит сообщений в час "
                    f"({hour_count}/{self.MAX_MESSAGES_PER_HOUR})"
                )

            # 3. АТОМАРНАЯ проверка и инкремент дневного лимита новых чатов (если нужно)
            day_count = 0
            if is_new_chat:
                day_ok, day_count = await self._atomic_check_and_increment(
                    redis,
                    day_key,
                    self.MAX_NEW_CHATS_PER_DAY,
                    2 * 24 * 60 * 60  # TTL = 2 дня
                )
                if not day_ok:
                    # Откатываем hour_count, так как мы не смогли зарегистрировать отправку
                    await self._safe_decrement(redis, hour_key)
                    if operator_hour_incremented and operator_hour_key:
                        await self._safe_decrement(redis, operator_hour_key)
                    if operator_day_incremented and operator_day_key:
                        await self._safe_decrement(redis, operator_day_key)
                    return False, (
                        f"⚠️ Превышен лимит новых чатов в день "
                        f"({day_count}/{self.MAX_NEW_CHATS_PER_DAY})"
                    )

                # Добавляем пользователя в set контактированных
                await redis.sadd(users_key, user_id)
                await redis.expire(users_key, 2 * 24 * 60 * 60)

            # Обновляем локальные счетчики для статистики
            self.message_count = hour_count
            self.daily_new_chats = day_count if is_new_chat else self.daily_new_chats
            self.last_message_time = now
            self.hour_start = now.replace(minute=0, second=0, microsecond=0)
            self.day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            logger.info(
                f"📊 Статистика: {self.message_count}/{self.MAX_MESSAGES_PER_HOUR} сообщений/час, "
                f"{self.daily_new_chats}/{self.MAX_NEW_CHATS_PER_DAY} новых чатов/день"
            )
            return True, "✅ OK"

        except Exception as exc:
            logger.warning(f"⚠️ Redis недоступен для anti-spam: {exc}")
            operator_limits = None
            if operator_id:
                operator_limits = await self._get_operator_limits(operator_id)
            return self._try_register_in_memory(
                now,
                user_id,
                is_new_chat,
                operator_id,
                operator_limits
            )

    def _try_register_in_memory(
        self,
        now: datetime,
        user_id: int,
        is_new_chat: bool,
        operator_id: Optional[int] = None,
        operator_limits: Optional[Tuple[int, int]] = None
    ) -> Tuple[bool, str]:
        if (now - self.hour_start) > timedelta(hours=1):
            logger.info(
                f"🔄 Сброс почасового счетчика. "
                f"Отправлено за час: {self.message_count}"
            )
            self.message_count = 0
            self.hour_start = now
            self.operator_hour_counts.clear()

        if (now - self.day_start) > timedelta(days=1):
            logger.info(
                f"🔄 Сброс дневного счетчика. "
                f"Новых чатов за день: {self.daily_new_chats}"
            )
            self.daily_new_chats = 0
            self.day_start = now
            self.sent_to_today.clear()
            self.operator_day_counts.clear()

        if self.message_count >= self.MAX_MESSAGES_PER_HOUR:
            return False, (
                f"⚠️ Превышен лимит сообщений в час "
                f"({self.message_count}/{self.MAX_MESSAGES_PER_HOUR})"
            )

        operator_hour_count = 0
        operator_day_count = 0
        if operator_id and operator_limits:
            operator_hour_limit, operator_day_limit = operator_limits
            operator_hour_count = self.operator_hour_counts.get(operator_id, 0)
            if operator_hour_count >= operator_hour_limit:
                return False, (
                    f"⚠️ Превышен лимит оператора в час "
                    f"({operator_hour_count}/{operator_hour_limit})"
                )
            operator_day_count = self.operator_day_counts.get(operator_id, 0)
            if operator_day_count >= operator_day_limit:
                return False, (
                    f"⚠️ Превышен лимит оператора в день "
                    f"({operator_day_count}/{operator_day_limit})"
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
        if operator_id and operator_limits:
            self.operator_hour_counts[operator_id] = operator_hour_count + 1
            self.operator_day_counts[operator_id] = operator_day_count + 1
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

    def update_limits(
        self,
        max_messages_per_hour: int,
        max_new_chats_per_day: int,
        min_delay_between_messages: int
    ) -> None:
        """Обновить лимиты без пересоздания менеджера."""
        self.MAX_MESSAGES_PER_HOUR = max_messages_per_hour
        self.MAX_NEW_CHATS_PER_DAY = max_new_chats_per_day
        self.MIN_DELAY_BETWEEN_MESSAGES = min_delay_between_messages
        logger.info(
            "🔧 Anti-Spam лимиты обновлены: %s msg/hour, %s new chats/day, %ss delay",
            self.MAX_MESSAGES_PER_HOUR,
            self.MAX_NEW_CHATS_PER_DAY,
            self.MIN_DELAY_BETWEEN_MESSAGES
        )
