"""
Cache Service — Redis-backed JSON cache with TTL and atomic rate-limiting.
"""

import json
import logging

import redis.asyncio as aioredis

from core.config import settings

logger = logging.getLogger(__name__)


class CacheService:
    def __init__(self) -> None:
        self.redis: aioredis.Redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )

    # ------------------------------------------------------------------
    # Generic primitives
    # ------------------------------------------------------------------

    async def get(self, key: str) -> dict | None:
        """Fetch a JSON-encoded value; returns None on miss or error."""
        try:
            raw = await self.redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Cache GET failed for key=%s: %s", key, exc)
            return None

    async def set(self, key: str, value: dict, ttl: int = 3600) -> None:
        """Store a dict as JSON with an expiry in seconds."""
        try:
            await self.redis.setex(key, ttl, json.dumps(value))
        except Exception as exc:
            logger.warning("Cache SET failed for key=%s: %s", key, exc)

    async def delete(self, key: str) -> None:
        """Delete a key."""
        try:
            await self.redis.delete(key)
        except Exception as exc:
            logger.warning("Cache DELETE failed for key=%s: %s", key, exc)

    async def increment(self, key: str, ttl: int | None = None) -> int:
        """Increment a key and optionally set its TTL on first creation."""
        try:
            val = await self.redis.incr(key)
            if ttl is not None and val == 1:
                await self.redis.expire(key, ttl)
            return val
        except Exception as exc:
            logger.warning("Cache INCR failed for key=%s: %s", key, exc)
            return 1

    # ------------------------------------------------------------------
    # Skill profile helpers
    # ------------------------------------------------------------------

    async def get_skill_profile(self, user_id: str) -> dict | None:
        return await self.get(f"skill:{user_id}")

    async def set_skill_profile(self, user_id: str, profile: dict) -> None:
        await self.set(f"skill:{user_id}", profile, ttl=86400)  # 24 h

    async def delete_skill_profile(self, user_id: str) -> None:
        await self.delete(f"skill:{user_id}")

    async def get_progress_dashboard(self, user_id: str) -> dict | None:
        return await self.get(f"progress_dashboard:{user_id}")

    async def set_progress_dashboard(self, user_id: str, data: dict) -> None:
        await self.set(f"progress_dashboard:{user_id}", data, ttl=300)  # 5 min

    async def delete_progress_dashboard(self, user_id: str) -> None:
        await self.delete(f"progress_dashboard:{user_id}")

    # ------------------------------------------------------------------
    # Roadmap helpers
    # ------------------------------------------------------------------

    async def cache_roadmap(self, user_id: str, roadmap: dict) -> None:
        await self.set(f"roadmap:{user_id}", roadmap, ttl=3600)

    async def get_cached_roadmap(self, user_id: str) -> dict | None:
        return await self.get(f"roadmap:{user_id}")

    # ------------------------------------------------------------------
    # Atomic rate-limiter
    # ------------------------------------------------------------------

    async def rate_limit(
        self,
        key: str,
        limit: int = 10,
        window: int = 60,
    ) -> bool:
        """
        Sliding-window rate-limiter using atomic INCR + EXPIRE.

        Returns True  → request is within the allowed limit.
        Returns False → limit exceeded; caller should reject the request.
        """
        try:
            pipe = self.redis.pipeline()
            await pipe.incr(key)
            await pipe.ttl(key)
            results = await pipe.execute()

            count: int = results[0]
            ttl_remaining: int = results[1]

            # Set expiry only on the first increment (TTL == -1)
            if ttl_remaining == -1:
                await self.redis.expire(key, window)

            return count <= limit
        except Exception as exc:
            logger.warning("Rate-limit check failed for key=%s: %s", key, exc)
            # Fail open: allow the request if Redis is unreachable
            return True


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

cache = CacheService()
