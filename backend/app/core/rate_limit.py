from __future__ import annotations
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class SimpleRateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding-window rate limit for expensive/abusable POST routes.

    This is intentionally simple (in-process memory, not Redis) — it is
    enough to stop a single client hammering the OpenAI/Gmail-backed
    endpoints from one Railway instance. If you scale to multiple instances
    behind a load balancer, replace this with a shared store (Redis) so
    limits are enforced across instances, not per-instance.
    """

    def __init__(self, app, *, limited_prefixes: tuple[str, ...], max_requests: int = 20, window_seconds: int = 60):
        super().__init__(app)
        self.limited_prefixes = limited_prefixes
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "POST" and any(path.startswith(p) for p in self.limited_prefixes):
            client_ip = request.client.host if request.client else "unknown"
            key = f"{client_ip}:{path}"
            now = time.monotonic()
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return JSONResponse(status_code=429, content={"detail": "Too many requests. Please slow down and try again shortly."})
            hits.append(now)
        return await call_next(request)
