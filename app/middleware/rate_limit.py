import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter. For production, use Redis-based sliding window."""

    def __init__(self, app, default_rpm: int = 60):
        super().__init__(app)
        self.default_rpm = default_rpm
        self._buckets: dict[str, list[float]] = {}

    def _get_client_key(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _is_rate_limited(self, key: str) -> bool:
        now = time.time()
        window = 60.0
        if key not in self._buckets:
            self._buckets[key] = []

        # Clean old entries
        self._buckets[key] = [t for t in self._buckets[key] if now - t < window]

        if len(self._buckets[key]) >= self.default_rpm:
            return True

        self._buckets[key].append(now)
        return False

    async def dispatch(self, request: Request, call_next) -> Response:
        key = self._get_client_key(request)
        if self._is_rate_limited(key):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )
        return await call_next(request)
