import threading
from dataclasses import dataclass, field
from typing import Any


LLM_DURATION_BUCKETS_SECONDS = (
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
)


@dataclass(frozen=True)
class LLMCallMetricKey:
    model: str
    status: str
    error_code: str


@dataclass(frozen=True)
class LLMAttemptMetricKey:
    model: str
    status: str
    error_code: str


@dataclass
class LLMCallMetricValue:
    count: int = 0
    attempt_count: int = 0
    retry_count: int = 0
    duration_sum_seconds: float = 0.0
    buckets: dict[float, int] = field(
        default_factory=lambda: {bucket: 0 for bucket in LLM_DURATION_BUCKETS_SECONDS}
    )


class LLMRuntimeMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[LLMCallMetricKey, LLMCallMetricValue] = {}
        self._attempts: dict[LLMAttemptMetricKey, int] = {}

    def record_call(self, metrics: Any) -> None:
        data = metrics.to_safe_dict()
        model = str(data.get("model") or "")
        status = str(data.get("last_status") or "unknown")
        attempts = data.get("attempts") if isinstance(data.get("attempts"), list) else []
        attempt_count = _int_value(data.get("attempt_count"), len(attempts))
        retry_count = _int_value(data.get("retry_count"), max(0, attempt_count - 1))
        duration_seconds = max(_float_value(data.get("total_duration_ms"), 0.0) / 1000, 0.0)
        error_code = _call_error_code(status, attempts)

        with self._lock:
            self._record_call_locked(
                model=model,
                status=status,
                error_code=error_code,
                attempt_count=attempt_count,
                retry_count=retry_count,
                duration_seconds=duration_seconds,
            )
            for attempt in attempts:
                if not isinstance(attempt, dict):
                    continue
                key = LLMAttemptMetricKey(
                    model=model,
                    status=str(attempt.get("status") or "unknown"),
                    error_code=str(attempt.get("error_code") or "none"),
                )
                self._attempts[key] = self._attempts.get(key, 0) + 1

    def record_missing_api_key(self, *, model: str) -> None:
        with self._lock:
            self._record_call_locked(
                model=model,
                status="failed",
                error_code="missing_api_key",
                attempt_count=0,
                retry_count=0,
                duration_seconds=0.0,
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            calls = [
                {
                    "model": key.model,
                    "status": key.status,
                    "error_code": key.error_code,
                    "count": value.count,
                    "attempt_count": value.attempt_count,
                    "retry_count": value.retry_count,
                    "duration_seconds": {
                        "sum": value.duration_sum_seconds,
                        "avg": (
                            value.duration_sum_seconds / value.count
                            if value.count
                            else 0.0
                        ),
                        "buckets": {
                            **{
                                _bucket_label(bucket): count
                                for bucket, count in value.buckets.items()
                            },
                            "+Inf": value.count,
                        },
                    },
                }
                for key, value in sorted(
                    self._calls.items(),
                    key=lambda item: (item[0].model, item[0].status, item[0].error_code),
                )
            ]
            attempts = [
                {
                    "model": key.model,
                    "status": key.status,
                    "error_code": key.error_code,
                    "count": count,
                }
                for key, count in sorted(
                    self._attempts.items(),
                    key=lambda item: (item[0].model, item[0].status, item[0].error_code),
                )
            ]
        return {
            "call_count": sum(item["count"] for item in calls),
            "attempt_count": sum(item["count"] for item in attempts),
            "retry_count": sum(item["retry_count"] for item in calls),
            "calls": calls,
            "attempts": attempts,
        }

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()
            self._attempts.clear()

    def _record_call_locked(
        self,
        *,
        model: str,
        status: str,
        error_code: str,
        attempt_count: int,
        retry_count: int,
        duration_seconds: float,
    ) -> None:
        key = LLMCallMetricKey(
            model=model,
            status=status,
            error_code=error_code,
        )
        value = self._calls.setdefault(key, LLMCallMetricValue())
        value.count += 1
        value.attempt_count += attempt_count
        value.retry_count += retry_count
        value.duration_sum_seconds += duration_seconds
        for bucket in LLM_DURATION_BUCKETS_SECONDS:
            if duration_seconds <= bucket:
                value.buckets[bucket] += 1


_llm_runtime_metrics = LLMRuntimeMetrics()


def record_llm_call(metrics: Any) -> None:
    _llm_runtime_metrics.record_call(metrics)


def record_llm_missing_api_key(*, model: str) -> None:
    _llm_runtime_metrics.record_missing_api_key(model=model)


def get_llm_metrics_snapshot() -> dict[str, Any]:
    return _llm_runtime_metrics.snapshot()


def reset_llm_metrics() -> None:
    _llm_runtime_metrics.reset()


def _call_error_code(status: str, attempts: list[Any]) -> str:
    if status == "succeeded":
        return "none"
    for attempt in reversed(attempts):
        if isinstance(attempt, dict) and attempt.get("error_code"):
            return str(attempt["error_code"])
    return "unknown"


def _int_value(value: object, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _float_value(value: object, default: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _bucket_label(bucket: float) -> str:
    return f"{bucket:g}"
