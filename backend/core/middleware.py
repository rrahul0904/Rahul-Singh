"""
UMA Platform — Security Middleware
Rate limiting · Request size limits · Audit logging · Security headers
"""

import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("uma.middleware")


# ═══════════════════════════════════════════════════════════════
# Rate Limiter (Redis-backed with in-memory fallback)
# ═══════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Sliding window rate limiter.
    Uses Redis if available, in-memory otherwise (not cluster-safe without Redis).
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self._redis = None
        self._memory: Dict[str, list] = {}

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        if not self.redis_url:
            return None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            await self._redis.ping()
            return self._redis
        except Exception as e:
            logger.warning(f"Rate limiter: Redis unavailable ({e}) — using in-memory")
            self._redis = None
            return None

    async def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """
        Returns (allowed, remaining).
        key: unique identifier (e.g. "login:ip:1.2.3.4" or "api:user:abc123")
        """
        now = time.time()
        redis = await self._get_redis()

        if redis:
            # Redis sorted set approach
            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, now - window_seconds)
            pipe.zadd(key, {str(uuid.uuid4()): now})
            pipe.zcard(key)
            pipe.expire(key, window_seconds)
            results = await pipe.execute()
            count = results[2]
            return count <= limit, max(0, limit - count)

        # In-memory fallback
        requests = self._memory.setdefault(key, [])
        cutoff = now - window_seconds
        requests[:] = [t for t in requests if t > cutoff]
        requests.append(now)
        return len(requests) <= limit, max(0, limit - len(requests))


_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        import os
        _limiter = RateLimiter(redis_url=os.getenv("REDIS_URL"))
    return _limiter


# ═══════════════════════════════════════════════════════════════
# Middleware: Rate Limiting
# ═══════════════════════════════════════════════════════════════

# Per-route limits: (requests per window, window in seconds)
RATE_LIMITS = {
    "/api/auth/login":    (10,  60),     # 10/min per IP
    "/api/auth/register": (5,   300),    # 5 per 5min per IP
    "/api/ai/":           (60,  60),     # 60/min per user (AI is expensive)
    "/api/snowflake/query": (30, 60),    # 30 queries/min per user
}
DEFAULT_LIMIT = (300, 60)  # 300/min per user globally


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Skip rate-limit for health checks and static
        if path in ("/api/health", "/api/health/ready", "/api/health/live", "/"):
            return await call_next(request)

        # Find applicable limit
        limit, window = DEFAULT_LIMIT
        for prefix, (l, w) in RATE_LIMITS.items():
            if path.startswith(prefix):
                limit, window = l, w
                break

        # Build rate-limit key
        user_id = getattr(request.state, "user_id", None)
        ip = request.client.host if request.client else "unknown"
        key = f"rl:{path}:{user_id or f'ip:{ip}'}"

        allowed, remaining = await get_rate_limiter().check(key, limit, window)

        if not allowed:
            logger.warning(f"Rate limit hit: {key}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": f"Rate limit exceeded: {limit} requests per {window}s"},
                headers={
                    "X-RateLimit-Limit":     str(limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After":           str(window),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"]     = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


# ═══════════════════════════════════════════════════════════════
# Middleware: Request Size Limit
# ═══════════════════════════════════════════════════════════════

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body exceeds MAX_REQUEST_BYTES."""

    MAX_REQUEST_BYTES = 10 * 1024 * 1024  # 10 MB default

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        cl = request.headers.get("content-length")
        if cl and int(cl) > self.MAX_REQUEST_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": f"Request body exceeds {self.MAX_REQUEST_BYTES} bytes"},
            )
        return await call_next(request)


# ═══════════════════════════════════════════════════════════════
# Middleware: Security Headers
# ═══════════════════════════════════════════════════════════════

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add common security headers to every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"]   = "nosniff"
        response.headers["X-Frame-Options"]          = "DENY"
        response.headers["Referrer-Policy"]          = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"]       = "geolocation=(), microphone=(), camera=()"
        # HSTS only over HTTPS — safe to always set; browsers ignore over HTTP
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# ═══════════════════════════════════════════════════════════════
# Middleware: Request ID + Structured Logging
# ═══════════════════════════════════════════════════════════════

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assign a unique ID to each request for log correlation.
    Reads incoming X-Request-ID if present (useful behind ingress), else generates one.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.time()
        response: Response
        try:
            response = await call_next(request)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.exception(
                f"request_failed request_id={request_id} "
                f"method={request.method} path={request.url.path} "
                f"duration_ms={duration_ms} error={type(e).__name__}"
            )
            raise

        duration_ms = int((time.time() - start) * 1000)
        logger.info(
            f"request method={request.method} path={request.url.path} "
            f"status={response.status_code} duration_ms={duration_ms} "
            f"request_id={request_id} "
            f"user={getattr(request.state, 'user_id', '-')} "
            f"ip={request.client.host if request.client else '-'}"
        )
        response.headers["X-Request-ID"] = request_id
        return response
