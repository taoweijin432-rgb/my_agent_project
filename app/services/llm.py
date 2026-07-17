import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.services.llm_metrics import record_llm_call, record_llm_missing_api_key


class LLMError(RuntimeError):
    """Raised when the model call fails."""

    def __init__(self, *args: object, usage: Any | None = None) -> None:
        super().__init__(*args)
        self.usage = usage


class MissingApiKeyError(LLMError):
    """Raised when no model API key is configured."""


@dataclass(frozen=True)
class LLMCallAttemptMetrics:
    attempt: int
    duration_ms: float
    status: str
    error_code: str | None = None
    error_type: str | None = None
    retryable: bool | None = None
    next_retry_delay_seconds: float | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "attempt": self.attempt,
            "duration_ms": self.duration_ms,
            "status": self.status,
        }
        if self.error_code:
            data["error_code"] = self.error_code
        if self.error_type:
            data["error_type"] = self.error_type
        if self.retryable is not None:
            data["retryable"] = self.retryable
        if self.next_retry_delay_seconds is not None:
            data["next_retry_delay_seconds"] = self.next_retry_delay_seconds
        return data


@dataclass(frozen=True)
class LLMCallMetrics:
    model: str
    base_url: str
    timeout_seconds: int
    max_retries: int
    retry_backoff_seconds: float
    attempts: tuple[LLMCallAttemptMetrics, ...]

    def to_safe_dict(self) -> dict[str, Any]:
        total_duration_ms = round(sum(attempt.duration_ms for attempt in self.attempts), 3)
        last_status = self.attempts[-1].status if self.attempts else "not_started"
        return {
            "model": self.model,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "attempt_count": len(self.attempts),
            "retry_count": max(0, len(self.attempts) - 1),
            "total_duration_ms": total_duration_ms,
            "last_status": last_status,
            "attempts": [attempt.to_safe_dict() for attempt in self.attempts],
        }


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._local = threading.local()
        self.last_call_metrics: LLMCallMetrics | None = None

    @property
    def last_call_metrics(self) -> LLMCallMetrics | None:
        return getattr(self._local, "last_call_metrics", None)

    @last_call_metrics.setter
    def last_call_metrics(self, value: LLMCallMetrics | None) -> None:
        self._local.last_call_metrics = value

    def generate_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.last_call_metrics = None
        if not self.settings.zhipu_api_key:
            record_llm_missing_api_key(model=self.settings.zhipu_chat_model)
            raise MissingApiKeyError(
                "ZHIPU_API_KEY is not configured. Set it in the environment or .env/config.py."
            )

        payload = {
            "model": self.settings.zhipu_chat_model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.zhipu_api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        attempts: list[LLMCallAttemptMetrics] = []
        max_attempts = self.settings.llm_max_retries + 1
        for attempt in range(1, max_attempts + 1):
            started_at = time.perf_counter()
            try:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    response = client.post(self._chat_url(), headers=headers, json=payload)
                    response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                parsed = json.loads(_extract_json(content))
                attempts.append(
                    LLMCallAttemptMetrics(
                        attempt=attempt,
                        duration_ms=_elapsed_ms(started_at),
                        status="succeeded",
                    )
                )
                metrics = self._build_metrics(attempts)
                self.last_call_metrics = metrics
                record_llm_call(metrics)
                return parsed
            except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
                last_error = exc
                error_code = _llm_error_code(exc)
                retryable = _llm_error_retryable(error_code)
                will_retry = retryable and attempt < max_attempts
                retry_delay_seconds = (
                    _retry_delay_seconds(
                        self.settings.llm_retry_backoff_seconds,
                        failed_attempt=attempt,
                    )
                    if will_retry
                    else None
                )
                attempts.append(
                    LLMCallAttemptMetrics(
                        attempt=attempt,
                        duration_ms=_elapsed_ms(started_at),
                        status="failed",
                        error_code=error_code,
                        error_type=type(exc).__name__,
                        retryable=retryable,
                        next_retry_delay_seconds=retry_delay_seconds,
                    )
                )
                self.last_call_metrics = self._build_metrics(attempts)
                if not will_retry:
                    break
                if retry_delay_seconds and retry_delay_seconds > 0:
                    time.sleep(retry_delay_seconds)

        if self.last_call_metrics is not None:
            record_llm_call(self.last_call_metrics)
        raise LLMError(f"LLM request failed: {last_error}") from last_error

    def _chat_url(self) -> str:
        base_url = self.settings.zhipu_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _build_metrics(self, attempts: list[LLMCallAttemptMetrics]) -> LLMCallMetrics:
        return LLMCallMetrics(
            model=self.settings.zhipu_chat_model,
            base_url=self.settings.zhipu_base_url.rstrip("/"),
            timeout_seconds=self.settings.llm_timeout_seconds,
            max_retries=self.settings.llm_max_retries,
            retry_backoff_seconds=self.settings.llm_retry_backoff_seconds,
            attempts=tuple(attempts),
        )


def _extract_json(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 3)


def _llm_error_code(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 429:
            return "rate_limited"
        if status_code >= 500:
            return "http_5xx"
        if status_code >= 400:
            return "http_4xx"
        return "http_status"
    if isinstance(exc, httpx.HTTPError):
        return "http_error"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, (KeyError, IndexError)):
        return "malformed_response"
    return "unknown"


def _llm_error_retryable(error_code: str) -> bool:
    return error_code in {
        "timeout",
        "rate_limited",
        "http_5xx",
        "http_error",
        "invalid_json",
        "malformed_response",
    }


def _retry_delay_seconds(base_delay_seconds: float, *, failed_attempt: int) -> float:
    if base_delay_seconds <= 0:
        return 0.0
    return round(base_delay_seconds * (2 ** (failed_attempt - 1)), 3)
