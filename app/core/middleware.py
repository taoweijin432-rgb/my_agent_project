import hashlib
import json
import logging
import threading
import time
from collections import deque
from math import ceil
from typing import Awaitable, Callable, Deque
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.services.http_metrics import record_http_request


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
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _request_id(request)
        request.state.request_id = request_id
        start = time.perf_counter()
        status_code = 500
        response: Response

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
            record_http_request(
                method=request.method,
                route=_request_route(request),
                status_code=status_code,
                duration_seconds=time.perf_counter() - start,
            )
            _log_request(request, request_id, status_code, start, settings=settings, failed=True)
            raise

        duration_seconds = time.perf_counter() - start
        duration_ms = duration_seconds * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-ms"] = f"{duration_ms:.2f}"
        record_http_request(
            method=request.method,
            route=_request_route(request),
            status_code=status_code,
            duration_seconds=duration_seconds,
        )
        if settings.request_log_enabled:
            _log_request(request, request_id, status_code, start, settings=settings)
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


def _request_route(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path or "unknown"


def _log_request(
    request: Request,
    request_id: str,
    status_code: int,
    start: float,
    *,
    settings: Settings,
    failed: bool = False,
) -> None:
    duration_ms = (time.perf_counter() - start) * 1000
    level = logging.ERROR if failed or status_code >= 500 else logging.INFO
    client_host = request.client.host if request.client else "unknown"
    if settings.request_log_format == "json":
        logger.log(
            level,
            json.dumps(
                {
                    "event": "request",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                    "request_id": request_id,
                    "client": client_host,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        return

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
