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
    except (redis.RedisError, redis.ConnectionError, OSError) as exc:  # Fixed #125
        _available = False
        logger.warning(f"⚠️ Redis недоступен: {exc}")
        return None


# Magic Link Authentication helpers (Fix #169)

async def save_magic_link_token(token: str, ttl_seconds: int = 300) -> bool:
    """
    Save magic link token to Redis with TTL.

    Fix #169: Magic link tokens are one-time use with 5 minute expiry.

    Args:
        token: UUID token
        ttl_seconds: Time to live in seconds (default: 300 = 5 minutes)

    Returns:
        bool: True if saved successfully, False if Redis unavailable
    """
    r = await get_redis()
    if not r:
        logger.warning("⚠️ Redis недоступен - не могу сохранить magic link token")
        return False

    try:
        # Key format: magic_link:{token}
        # Value: {"created_at": timestamp, "used": false}
        import json
        from datetime import datetime

        data = {
            "created_at": datetime.utcnow().isoformat(),
            "used": False
        }

        await r.setex(f"magic_link:{token}", ttl_seconds, json.dumps(data))
        logger.info(f"✅ Magic link token сохранен: {token[:8]}... (TTL: {ttl_seconds}s)")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения magic link token: {e}")
        return False


async def get_magic_link_token(token: str) -> Optional[dict]:
    """
    Get magic link token data from Redis.

    Args:
        token: UUID token

    Returns:
        dict: Token data {"created_at": ..., "used": ...} or None if not found
    """
    r = await get_redis()
    if not r:
        return None

    try:
        import json
        data_str = await r.get(f"magic_link:{token}")
        if not data_str:
            return None

        return json.loads(data_str)
    except Exception as e:
        logger.error(f"❌ Ошибка получения magic link token: {e}")
        return None


async def mark_magic_link_token_used(token: str) -> bool:
    """
    Mark magic link token as used (prevents reuse).

    Args:
        token: UUID token

    Returns:
        bool: True if marked successfully, False otherwise
    """
    r = await get_redis()
    if not r:
        return False

    try:
        import json
        from datetime import datetime

        # Get current data
        data_str = await r.get(f"magic_link:{token}")
        if not data_str:
            return False

        data = json.loads(data_str)
        data["used"] = True
        data["used_at"] = datetime.utcnow().isoformat()

        # Update with remaining TTL
        ttl = await r.ttl(f"magic_link:{token}")
        if ttl > 0:
            await r.setex(f"magic_link:{token}", ttl, json.dumps(data))
            logger.info(f"✅ Magic link token помечен как использованный: {token[:8]}...")
            return True
        else:
            # Token expired
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка пометки magic link token как использованный: {e}")
        return False


async def delete_magic_link_token(token: str) -> bool:
    """
    Delete magic link token from Redis.

    Args:
        token: UUID token

    Returns:
        bool: True if deleted successfully, False otherwise
    """
    r = await get_redis()
    if not r:
        return False

    try:
        await r.delete(f"magic_link:{token}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка удаления magic link token: {e}")
        return False
