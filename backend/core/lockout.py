"""
UMA Platform — Account Lockout
Tracks failed login attempts per account and locks after N failures.
Uses Redis for fast access with in-memory fallback.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("uma.lockout")


class AccountLockout:
    MAX_FAILURES       = 5        # Lock after 5 failed attempts
    LOCKOUT_MINUTES    = 15       # Lock for 15 minutes
    ATTEMPT_WINDOW_MIN = 10       # Count failures within a 10-min window

    def __init__(self):
        self._redis = None
        self._memory: dict = {}

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            return None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            return self._redis
        except Exception:
            self._redis = None
            return None

    async def record_failure(self, email: str) -> int:
        """Record a failed login attempt. Returns current failure count."""
        key = f"lockout:fail:{email.lower()}"
        redis = await self._get_redis()

        if redis:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.ATTEMPT_WINDOW_MIN * 60)
            count, _ = await pipe.execute()
            if count >= self.MAX_FAILURES:
                await redis.setex(
                    f"lockout:locked:{email.lower()}",
                    self.LOCKOUT_MINUTES * 60, "1"
                )
            return count

        # In-memory fallback
        now = datetime.utcnow()
        failures = self._memory.setdefault(key, [])
        cutoff = now - timedelta(minutes=self.ATTEMPT_WINDOW_MIN)
        failures[:] = [f for f in failures if f > cutoff]
        failures.append(now)

        if len(failures) >= self.MAX_FAILURES:
            self._memory[f"locked:{email.lower()}"] = now + timedelta(minutes=self.LOCKOUT_MINUTES)
        return len(failures)

    async def clear_failures(self, email: str):
        """Call after successful login."""
        key = f"lockout:fail:{email.lower()}"
        redis = await self._get_redis()
        if redis:
            await redis.delete(key, f"lockout:locked:{email.lower()}")
        else:
            self._memory.pop(key, None)
            self._memory.pop(f"locked:{email.lower()}", None)

    async def is_locked(self, email: str) -> tuple[bool, Optional[int]]:
        """Returns (is_locked, seconds_remaining)."""
        key = f"lockout:locked:{email.lower()}"
        redis = await self._get_redis()

        if redis:
            ttl = await redis.ttl(key)
            if ttl > 0:
                return True, ttl
            return False, None

        expiry = self._memory.get(f"locked:{email.lower()}")
        if expiry and expiry > datetime.utcnow():
            remaining = int((expiry - datetime.utcnow()).total_seconds())
            return True, remaining
        return False, None


_lockout: Optional[AccountLockout] = None


def get_lockout() -> AccountLockout:
    global _lockout
    if _lockout is None:
        _lockout = AccountLockout()
    return _lockout
