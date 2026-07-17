import json

import httpx
import pytest

from app.core.config import Settings
from app.services.llm import LLMClient, LLMError, MissingApiKeyError
from app.services.llm_metrics import get_llm_metrics_snapshot, reset_llm_metrics


@pytest.fixture(autouse=True)
def clear_llm_metrics() -> None:
    reset_llm_metrics()
    yield
    reset_llm_metrics()


class FakeResponse:
    def __init__(self, content: str = '{"ok": true}', status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.test/chat/completions")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("upstream failed", request=request, response=response)

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": self.content,
                    }
                }
            ]
        }


def test_llm_client_records_safe_retry_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes: list[object] = [
        httpx.ReadTimeout("slow upstream"),
        FakeResponse('{"ok": true}'),
    ]

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(
            self,
            _url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            assert "Authorization" in headers
            assert "messages" in json
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    sleep_calls: list[float] = []
    monkeypatch.setattr("app.services.llm.httpx.Client", FakeClient)
    monkeypatch.setattr("app.services.llm.time.sleep", sleep_calls.append)

    client = LLMClient(
        Settings(
            zhipu_api_key="secret-value-for-tests",
            zhipu_chat_model="glm-test",
            llm_timeout_seconds=3,
            llm_max_retries=1,
            llm_retry_backoff_seconds=0.25,
        )
    )

    assert client.generate_json([{"role": "user", "content": "return json"}]) == {"ok": True}

    assert client.last_call_metrics is not None
    metrics = client.last_call_metrics.to_safe_dict()
    assert metrics["model"] == "glm-test"
    assert metrics["timeout_seconds"] == 3
    assert metrics["retry_backoff_seconds"] == 0.25
    assert metrics["attempt_count"] == 2
    assert metrics["retry_count"] == 1
    assert metrics["last_status"] == "succeeded"
    assert metrics["attempts"][0]["error_code"] == "timeout"
    assert metrics["attempts"][0]["retryable"] is True
    assert metrics["attempts"][0]["next_retry_delay_seconds"] == 0.25
    assert sleep_calls == [0.25]
    serialized = json.dumps(metrics)
    assert "secret-value-for-tests" not in serialized
    assert "return json" not in serialized
    runtime = get_llm_metrics_snapshot()
    assert runtime["call_count"] == 1
    assert runtime["attempt_count"] == 2
    assert runtime["retry_count"] == 1
    assert runtime["calls"][0]["model"] == "glm-test"
    assert runtime["calls"][0]["status"] == "succeeded"
    assert runtime["calls"][0]["error_code"] == "none"
    assert runtime["attempts"] == [
        {
            "model": "glm-test",
            "status": "failed",
            "error_code": "timeout",
            "count": 1,
        },
        {
            "model": "glm-test",
            "status": "succeeded",
            "error_code": "none",
            "count": 1,
        },
    ]


def test_llm_client_records_failed_attempt_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(
            self,
            _url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            return FakeResponse("not-json")

    monkeypatch.setattr("app.services.llm.httpx.Client", FakeClient)

    client = LLMClient(
        Settings(
            zhipu_api_key="secret-value-for-tests",
            llm_max_retries=0,
        )
    )

    with pytest.raises(LLMError):
        client.generate_json([{"role": "user", "content": "return json"}])

    assert client.last_call_metrics is not None
    metrics = client.last_call_metrics.to_safe_dict()
    assert metrics["attempt_count"] == 1
    assert metrics["last_status"] == "failed"
    assert metrics["attempts"][0]["error_code"] == "invalid_json"
    runtime = get_llm_metrics_snapshot()
    assert runtime["call_count"] == 1
    assert runtime["attempt_count"] == 1
    assert runtime["retry_count"] == 0
    assert runtime["calls"][0]["status"] == "failed"
    assert runtime["calls"][0]["error_code"] == "invalid_json"


def test_llm_client_does_not_retry_non_retryable_http_4xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleep_calls: list[float] = []

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(
            self,
            _url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            nonlocal calls
            calls += 1
            return FakeResponse(status_code=401)

    monkeypatch.setattr("app.services.llm.httpx.Client", FakeClient)
    monkeypatch.setattr("app.services.llm.time.sleep", sleep_calls.append)

    client = LLMClient(
        Settings(
            zhipu_api_key="secret-value-for-tests",
            llm_max_retries=2,
            llm_retry_backoff_seconds=0.25,
        )
    )

    with pytest.raises(LLMError):
        client.generate_json([{"role": "user", "content": "return json"}])

    assert calls == 1
    assert sleep_calls == []
    assert client.last_call_metrics is not None
    metrics = client.last_call_metrics.to_safe_dict()
    assert metrics["attempt_count"] == 1
    assert metrics["retry_count"] == 0
    assert metrics["last_status"] == "failed"
    assert metrics["attempts"][0]["error_code"] == "http_4xx"
    assert metrics["attempts"][0]["retryable"] is False
    assert "next_retry_delay_seconds" not in metrics["attempts"][0]


def test_llm_client_retries_rate_limited_http_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [FakeResponse(status_code=429), FakeResponse('{"ok": true}')]
    sleep_calls: list[float] = []

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(
            self,
            _url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            assert "Authorization" in headers
            assert "messages" in json
            return responses.pop(0)

    monkeypatch.setattr("app.services.llm.httpx.Client", FakeClient)
    monkeypatch.setattr("app.services.llm.time.sleep", sleep_calls.append)

    client = LLMClient(
        Settings(
            zhipu_api_key="secret-value-for-tests",
            llm_max_retries=1,
            llm_retry_backoff_seconds=0.25,
        )
    )

    assert client.generate_json([{"role": "user", "content": "return json"}]) == {"ok": True}

    assert sleep_calls == [0.25]
    assert client.last_call_metrics is not None
    metrics = client.last_call_metrics.to_safe_dict()
    assert metrics["attempt_count"] == 2
    assert metrics["retry_count"] == 1
    assert metrics["last_status"] == "succeeded"
    assert metrics["attempts"][0]["error_code"] == "rate_limited"
    assert metrics["attempts"][0]["retryable"] is True
    assert metrics["attempts"][0]["next_retry_delay_seconds"] == 0.25
    runtime = get_llm_metrics_snapshot()
    assert runtime["call_count"] == 1
    assert runtime["attempt_count"] == 2
    assert runtime["retry_count"] == 1
    assert {
        (attempt["status"], attempt["error_code"], attempt["count"])
        for attempt in runtime["attempts"]
    } == {
        ("failed", "rate_limited", 1),
        ("succeeded", "none", 1),
    }


def test_llm_client_records_missing_api_key_runtime_metric() -> None:
    client = LLMClient(Settings(zhipu_api_key=None, zhipu_chat_model="glm-test"))

    with pytest.raises(MissingApiKeyError):
        client.generate_json([{"role": "user", "content": "return json"}])

    assert client.last_call_metrics is None
    runtime = get_llm_metrics_snapshot()
    assert runtime["call_count"] == 1
    assert runtime["attempt_count"] == 0
    assert runtime["retry_count"] == 0
    assert runtime["calls"][0]["model"] == "glm-test"
    assert runtime["calls"][0]["status"] == "failed"
    assert runtime["calls"][0]["error_code"] == "missing_api_key"
    serialized = json.dumps(runtime)
    assert "return json" not in serialized
