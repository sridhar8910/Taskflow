"""
Redis caching helpers for task list responses.

Cache key format:
    tasks:user:{user_id}:{md5(sorted filter params as JSON)}

Invalidation:
    On any task mutation (create/update/delete), delete all keys matching
    tasks:user:{user_id}:* for every affected user (owner, old assignee,
    new assignee). Uses SCAN to avoid KEYS in production Redis.
"""

import hashlib
import json
import logging
import uuid
from typing import Any

from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "tasks:user"


def make_cache_key(user_id: uuid.UUID, filters: dict[str, Any]) -> str:
    """
    Build a deterministic cache key for a user + filter combination.
    Filters are sorted before hashing so key order doesn't matter.
    """
    canonical = json.dumps(filters, sort_keys=True, default=str)
    digest = hashlib.md5(canonical.encode()).hexdigest()  # noqa: S324 — not security-sensitive
    return f"{_KEY_PREFIX}:{user_id}:{digest}"


def _user_pattern(user_id: uuid.UUID) -> str:
    return f"{_KEY_PREFIX}:{user_id}:*"


async def get_cached(redis: Redis, key: str) -> str | None:
    """Return cached value or None on miss/error."""
    try:
        return await redis.get(key)
    except Exception as exc:
        logger.warning("Redis cache read failed (falling back to DB): %s", exc)
        return None


async def set_cached(redis: Redis, key: str, value: str) -> None:
    """Write value with configured TTL."""
    try:
        await redis.set(key, value, ex=settings.cache_ttl_seconds)
    except Exception as exc:
        logger.warning("Redis cache write failed: %s", exc)


async def invalidate_user_tasks(redis: Redis, *user_ids: uuid.UUID | None) -> None:
    """
    Delete all cached task-list keys for the given user IDs.
    Accepts None values so callers can pass old/new assignee IDs without
    guarding against None.

    Uses SCAN with a cursor to avoid blocking Redis with KEYS in production.
    """
    try:
        for user_id in user_ids:
            if user_id is None:
                continue
            pattern = _user_pattern(user_id)
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await redis.delete(*keys)
                if cursor == 0:
                    break
    except Exception as exc:
        logger.warning("Redis cache invalidation failed: %s", exc)
