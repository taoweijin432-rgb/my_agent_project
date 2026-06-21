import hashlib
import logging
import threading
import time
from collections import deque
from math import ceil
from typing import Deque
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings


logger = logging.getLogger("app.requests")


class InMemoryRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, identity: str, now: float | None = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else now
        window_start = current - self.window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(identity, deque())
            while bucket and bucket[0] <= window_start:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                retry_after = ceil(self.window_seconds - (current - bucket[0]))
                return False, max(retry_after, 1)
            bucket.append(current)
            return True, 0


def add_request_middleware(app: FastAPI, settings: Settings) -> None:
    limiter = InMemoryRateLimiter(
        settings.rate_limit_requests,
        settings.rate_limit_window_seconds,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:
        request_id = _request_id(request)
        request.state.request_id = request_id
        start = time.perf_counter()
        status_code = 500

        try:
            if _should_rate_limit(request, settings):
                allowed, retry_after = limiter.check(_client_identity(request))
                if not allowed:
                    response = JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded."},
                        headers={"Retry-After": str(retry_after)},
                    )
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
            status_code = response.status_code
        except Exception:
            _log_request(request, request_id, status_code, start, failed=True)
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-ms"] = f"{duration_ms:.2f}"
        if settings.request_log_enabled:
            _log_request(request, request_id, status_code, start)
        return response


def _should_rate_limit(request: Request, settings: Settings) -> bool:
    return (
        settings.rate_limit_enabled
        and request.method != "OPTIONS"
        and request.url.path.startswith("/api/v1/")
    )


def _client_identity(request: Request) -> str:
    api_key = request.headers.get("X-API-Key")
    if api_key:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        return f"api-key:{digest}"
    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"


def _request_id(request: Request) -> str:
    incoming = request.headers.get("X-Request-ID", "").strip()
    if incoming and len(incoming) <= 128:
        return incoming
    return uuid4().hex


def _log_request(
    request: Request,
    request_id: str,
    status_code: int,
    start: float,
    *,
    failed: bool = False,
) -> None:
    duration_ms = (time.perf_counter() - start) * 1000
    level = logging.ERROR if failed or status_code >= 500 else logging.INFO
    client_host = request.client.host if request.client else "unknown"
    logger.log(
        level,
        (
            "request "
            "method=%s path=%s status_code=%s duration_ms=%.2f "
            "request_id=%s client=%s"
        ),
        request.method,
        request.url.path,
        status_code,
        duration_ms,
        request_id,
        client_host,
    )
