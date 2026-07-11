import json
import logging
import time
from types import SimpleNamespace

from app.core.config import Settings
from app.core.middleware import _log_request


def _request(path: str = "/health") -> SimpleNamespace:
    return SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path=path),
        client=SimpleNamespace(host="127.0.0.1"),
    )


def test_log_request_can_emit_json(caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.requests")

    _log_request(
        _request("/api/v1/test-cases/generate"),
        "req-json",
        200,
        time.perf_counter(),
        settings=Settings(request_log_format="json"),
    )

    payload = json.loads(caplog.records[-1].getMessage())
    assert payload["event"] == "request"
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/v1/test-cases/generate"
    assert payload["status_code"] == 200
    assert payload["request_id"] == "req-json"
    assert payload["client"] == "127.0.0.1"
    assert payload["duration_ms"] >= 0


def test_log_request_keeps_text_format_by_default(caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.requests")

    _log_request(
        _request(),
        "req-text",
        200,
        time.perf_counter(),
        settings=Settings(),
    )

    message = caplog.records[-1].getMessage()
    assert "request method=GET path=/health status_code=200" in message
    assert "request_id=req-text" in message
