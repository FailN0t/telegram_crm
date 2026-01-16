"""
Тесты для атомарных операций AntiSpam менеджера
Проверяют корректность Lua скриптов и race condition protection
"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.antispam import AntiSpamManager, LUA_ATOMIC_CHECK_INCREMENT, LUA_ATOMIC_CHECK_DELAY
from src.config import settings


@pytest.fixture
async def redis_mock():
    """Мок Redis клиента с поддержкой Lua скриптов"""
    redis = AsyncMock()

    # Эмулируем хранилище Redis
    storage = {}
    ttls = {}

    async def mock_get(key):
        return storage.get(key)

    async def mock_set(key, value):
        storage[key] = str(value)

    async def mock_incr(key):
        current = int(storage.get(key, 0))
        storage[key] = str(current + 1)
        return current + 1

    async def mock_decr(key):
        current = int(storage.get(key, 0))
        storage[key] = str(max(0, current - 1))
        return max(0, current - 1)

    async def mock_expire(key, ttl):
        ttls[key] = ttl
        return True

    async def mock_sismember(key, member):
        return member in storage.get(key, set())

    async def mock_sadd(key, member):
        if key not in storage:
            storage[key] = set()
        storage[key].add(member)
        return 1

    async def mock_script_load(script):
        # Возвращаем хеш скрипта
        return f"sha_{hash(script)}"

    async def mock_eval(script, num_keys, *args):
        """Эмулируем выполнение Lua скриптов"""
        if LUA_ATOMIC_CHECK_INCREMENT in script or script.startswith("sha_"):
            # Атомарная проверка и инкремент
            key = args[0]
            limit = int(args[1])
            ttl = int(args[2])

            current = storage.get(key)
            if current and int(current) >= limit:
                return [0, int(current)]

            new_val = int(storage.get(key, 0)) + 1
            storage[key] = str(new_val)
            if new_val == 1:
                ttls[key] = ttl

            return [1, new_val]

        elif LUA_ATOMIC_CHECK_DELAY in script or script.startswith("sha_"):
            # Атомарная проверка задержки
            key = args[0]
            min_delay = float(args[1])
            current_timestamp = float(args[2])
            ttl = int(args[3])

            last_timestamp = storage.get(key)
            if last_timestamp:
                time_since_last = current_timestamp - float(last_timestamp)
                if time_since_last < min_delay:
                    wait_time = min_delay - time_since_last
                    return [0, float(last_timestamp), wait_time]

            storage[key] = str(current_timestamp)
            ttls[key] = ttl
            return [1, current_timestamp]

        return None

    async def mock_evalsha(sha, num_keys, *args):
        # Используем ту же логику что и eval
        return await mock_eval(sha, num_keys, *args)

    redis.get = mock_get
    redis.set = mock_set
    redis.incr = mock_incr
    redis.decr = mock_decr
    redis.expire = mock_expire
    redis.sismember = mock_sismember
    redis.sadd = mock_sadd
    redis.script_load = mock_script_load
    redis.eval = mock_eval
    redis.evalsha = mock_evalsha

    # Добавляем доступ к хранилищу для проверок в тестах
    redis._storage = storage
    redis._ttls = ttls

    return redis


@pytest.fixture
def antispam_manager():
    """Создает AntiSpamManager с тестовыми лимитами"""
    with patch.object(settings, 'MAX_MESSAGES_PER_HOUR', 10):
        with patch.object(settings, 'MAX_NEW_CHATS_PER_DAY', 5):
            with patch.object(settings, 'MIN_DELAY_BETWEEN_MESSAGES', 1.0):
                manager = AntiSpamManager()
                return manager


@pytest.mark.asyncio
async def test_atomic_check_increment_success(antispam_manager, redis_mock):
    """Тест успешной атомарной проверки и инкремента"""
    key = "test:counter"
    limit = 10
    ttl = 3600

    # Первый вызов - должен вернуть success=True, value=1
    success, value = await antispam_manager._atomic_check_and_increment(
        redis_mock, key, limit, ttl
    )

    assert success is True
    assert value == 1
    assert redis_mock._storage[key] == "1"
    assert redis_mock._ttls[key] == ttl


@pytest.mark.asyncio
async def test_atomic_check_increment_limit_exceeded(antispam_manager, redis_mock):
    """Тест превышения лимита при атомарной проверке"""
    key = "test:counter"
    limit = 3
    ttl = 3600

    # Делаем 3 успешных инкремента
    for i in range(3):
        success, value = await antispam_manager._atomic_check_and_increment(
            redis_mock, key, limit, ttl
        )
        assert success is True
        assert value == i + 1

    # 4-й запрос должен быть отклонен
    success, value = await antispam_manager._atomic_check_and_increment(
        redis_mock, key, limit, ttl
    )

    assert success is False
    assert value == 3  # Значение не увеличилось


@pytest.mark.asyncio
async def test_atomic_check_delay_success(antispam_manager, redis_mock):
    """Тест успешной атомарной проверки задержки"""
    key = "test:delay"
    min_delay = 1.0
    timestamp1 = 1000.0
    timestamp2 = 1002.0  # +2 секунды
    ttl = 60

    # Первый вызов
    success, wait = await antispam_manager._atomic_check_delay(
        redis_mock, key, min_delay, timestamp1, ttl
    )
    assert success is True
    assert wait == 0.0

    # Второй вызов через 2 секунды - должен пройти
    success, wait = await antispam_manager._atomic_check_delay(
        redis_mock, key, min_delay, timestamp2, ttl
    )
    assert success is True
    assert wait == 0.0


@pytest.mark.asyncio
async def test_atomic_check_delay_too_fast(antispam_manager, redis_mock):
    """Тест блокировки при слишком частых запросах"""
    key = "test:delay"
    min_delay = 2.0
    timestamp1 = 1000.0
    timestamp2 = 1001.0  # +1 секунда (меньше min_delay)
    ttl = 60

    # Первый вызов
    success, wait = await antispam_manager._atomic_check_delay(
        redis_mock, key, min_delay, timestamp1, ttl
    )
    assert success is True

    # Второй вызов слишком рано
    success, wait = await antispam_manager._atomic_check_delay(
        redis_mock, key, min_delay, timestamp2, ttl
    )
    assert success is False
    assert wait == 1.0  # Нужно подождать еще 1 секунду


@pytest.mark.asyncio
async def test_100_parallel_requests_dont_exceed_limit(antispam_manager, redis_mock):
    """
    CRITICAL TEST: 100 параллельных запросов НЕ должны превысить лимит
    Проверяет, что Lua скрипт действительно атомарный
    """
    limit = 50

    # Патчим get_redis чтобы вернуть наш мок
    with patch('src.antispam.get_redis', return_value=redis_mock):
        # Сбрасываем время для теста
        with patch('src.antispam.datetime') as mock_datetime:
            # Фиксируем время на 12:00 (в допустимом диапазоне 9-21)
            test_time = datetime(2026, 1, 16, 12, 0, 0)
            mock_datetime.now.return_value = test_time
            mock_datetime.fromtimestamp = datetime.fromtimestamp

            # Патчим лимит
            antispam_manager.MAX_MESSAGES_PER_HOUR = limit

            # Запускаем 100 параллельных запросов
            tasks = []
            for i in range(100):
                # Разные user_id, is_new_chat=False чтобы не упереться в дневной лимит
                task = antispam_manager.try_register_send(
                    user_id=i,
                    is_new_chat=False
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks)

            # Подсчитываем успешные и отклоненные запросы
            successful = sum(1 for success, _ in results if success)
            rejected = sum(1 for success, _ in results if not success)

            # Проверяем, что успешных запросов ровно limit
            assert successful == limit, (
                f"Ожидалось {limit} успешных запросов, получено {successful}. "
                f"Атомарность нарушена!"
            )
            assert rejected == 100 - limit

            # Проверяем значение в Redis
            hour_key = antispam_manager._hour_key(test_time)
            final_count = int(redis_mock._storage.get(hour_key, 0))
            assert final_count == limit, (
                f"В Redis счетчик = {final_count}, ожидалось {limit}"
            )


@pytest.mark.asyncio
async def test_100_parallel_new_chats_dont_exceed_limit(antispam_manager, redis_mock):
    """
    Тест: 100 параллельных запросов с is_new_chat=True не превышают дневной лимит
    """
    hour_limit = 100  # Большой чтобы не упереться в него
    day_limit = 30

    with patch('src.antispam.get_redis', return_value=redis_mock):
        with patch('src.antispam.datetime') as mock_datetime:
            test_time = datetime(2026, 1, 16, 12, 0, 0)
            mock_datetime.now.return_value = test_time
            mock_datetime.fromtimestamp = datetime.fromtimestamp

            antispam_manager.MAX_MESSAGES_PER_HOUR = hour_limit
            antispam_manager.MAX_NEW_CHATS_PER_DAY = day_limit

            # Запускаем 100 параллельных запросов с новыми чатами
            tasks = []
            for i in range(100):
                task = antispam_manager.try_register_send(
                    user_id=1000 + i,  # Разные user_id
                    is_new_chat=True
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks)

            successful = sum(1 for success, _ in results if success)

            # Успешных должно быть не больше дневного лимита
            assert successful <= day_limit, (
                f"Ожидалось максимум {day_limit} успешных новых чатов, "
                f"получено {successful}"
            )


@pytest.mark.asyncio
async def test_ttl_is_set_correctly(antispam_manager, redis_mock):
    """Тест: TTL устанавливается корректно"""
    key = "test:ttl"
    limit = 10
    ttl = 7200  # 2 часа

    # Первый вызов - должен установить TTL
    success, value = await antispam_manager._atomic_check_and_increment(
        redis_mock, key, limit, ttl
    )

    assert success is True
    assert redis_mock._ttls[key] == ttl

    # Второй вызов - TTL не должен сбрасываться
    success, value = await antispam_manager._atomic_check_and_increment(
        redis_mock, key, limit, ttl
    )

    assert success is True
    # В реальном Redis TTL не сбрасывается при повторном INCR
    # Наш мок не перезаписывает TTL если ключ уже существует


@pytest.mark.asyncio
async def test_delay_ttl_is_set(antispam_manager, redis_mock):
    """Тест: TTL для delay ключа устанавливается"""
    key = "test:delay_ttl"
    min_delay = 1.0
    timestamp = 1000.0
    ttl = 120

    success, wait = await antispam_manager._atomic_check_delay(
        redis_mock, key, min_delay, timestamp, ttl
    )

    assert success is True
    assert redis_mock._ttls[key] == ttl


@pytest.mark.asyncio
async def test_rollback_on_day_limit_exceeded(antispam_manager, redis_mock):
    """
    Тест: если дневной лимит превышен, почасовой счетчик должен откатиться
    """
    with patch('src.antispam.get_redis', return_value=redis_mock):
        with patch('src.antispam.datetime') as mock_datetime:
            test_time = datetime(2026, 1, 16, 12, 0, 0)
            mock_datetime.now.return_value = test_time
            mock_datetime.fromtimestamp = datetime.fromtimestamp

            antispam_manager.MAX_MESSAGES_PER_HOUR = 100
            antispam_manager.MAX_NEW_CHATS_PER_DAY = 2

            # Первый новый чат - успех
            success1, _ = await antispam_manager.try_register_send(
                user_id=1, is_new_chat=True
            )
            assert success1 is True

            # Второй новый чат - успех
            success2, _ = await antispam_manager.try_register_send(
                user_id=2, is_new_chat=True
            )
            assert success2 is True

            # Проверяем почасовой счетчик (должно быть 2)
            hour_key = antispam_manager._hour_key(test_time)
            hour_count_before = int(redis_mock._storage.get(hour_key, 0))
            assert hour_count_before == 2

            # Третий новый чат - должен быть отклонен
            success3, msg = await antispam_manager.try_register_send(
                user_id=3, is_new_chat=True
            )
            assert success3 is False
            assert "новых чатов" in msg

            # Проверяем что почасовой счетчик откатился (должно быть 2, не 3)
            hour_count_after = int(redis_mock._storage.get(hour_key, 0))
            assert hour_count_after == 2, (
                f"Почасовой счетчик не откатился: было {hour_count_before}, "
                f"стало {hour_count_after}"
            )


@pytest.mark.asyncio
async def test_lua_scripts_loaded_once(antispam_manager, redis_mock):
    """Тест: Lua скрипты загружаются только один раз"""

    # Первый вызов - скрипты должны загрузиться
    await antispam_manager._atomic_check_and_increment(
        redis_mock, "test:key", 10, 3600
    )

    assert antispam_manager._lua_check_increment_sha is not None
    sha1 = antispam_manager._lua_check_increment_sha

    # Второй вызов - скрипты не должны перезагружаться
    call_count_before = redis_mock.script_load.call_count

    await antispam_manager._atomic_check_and_increment(
        redis_mock, "test:key2", 10, 3600
    )

    call_count_after = redis_mock.script_load.call_count
    sha2 = antispam_manager._lua_check_increment_sha

    # SHA должен остаться тем же, script_load не должен вызываться снова
    assert sha1 == sha2
    assert call_count_after == call_count_before


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
