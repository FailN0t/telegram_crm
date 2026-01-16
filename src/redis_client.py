"""
Redis client helper (async).
"""

from __future__ import annotations

import time
from typing import Optional

import redis.asyncio as redis

from src.config import settings
from src.logger import logger


_redis_client: Optional[redis.Redis] = None
_last_check: float = 0.0
_available: bool = False


async def get_redis() -> Optional[redis.Redis]:
    global _redis_client, _last_check, _available

    now = time.time()
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

    if _available and (now - _last_check) < 30:
        return _redis_client

    if not _available and (now - _last_check) < 30:
        return None

    _last_check = now
    try:
        await _redis_client.ping()
        _available = True
        return _redis_client
    except Exception as exc:
        _available = False
        logger.warning(f"⚠️ Redis недоступен: {exc}")
        return None
