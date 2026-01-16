"""
Simple rate limiter with Redis fallback.
"""

import asyncio
import time
from typing import Dict, Tuple

from src.redis_client import get_redis


_memory_counts: Dict[Tuple[str, int], int] = {}
_lock = asyncio.Lock()


async def check_rate_limit(
    key: str,
    limit: int,
    window_seconds: int = 60,
    prefix: str = "ratelimit"
) -> Tuple[bool, int]:
    if limit <= 0:
        return True, 0

    now = time.time()
    window = int(now / window_seconds)
    redis_key = f"{prefix}:{key}:{window}"

    redis = await get_redis()
    if redis:
        count = await redis.incr(redis_key)
        if count == 1:
            await redis.expire(redis_key, window_seconds + 1)
        return count <= limit, int(count)

    bucket_key = (key, window)
    async with _lock:
        count = _memory_counts.get(bucket_key, 0) + 1
        _memory_counts[bucket_key] = count
        if len(_memory_counts) > 2048:
            stale_window = window - 2
            for old_key in list(_memory_counts.keys()):
                if old_key[1] < stale_window:
                    _memory_counts.pop(old_key, None)
    return count <= limit, count
