import threading
from dataclasses import dataclass, field
from typing import Any


HTTP_DURATION_BUCKETS_SECONDS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


@dataclass(frozen=True)
class HttpRequestMetricKey:
    method: str
    route: str
    status_code: int


@dataclass
class HttpRequestMetricValue:
    count: int = 0
    duration_sum_seconds: float = 0.0
    buckets: dict[float, int] = field(
        default_factory=lambda: {bucket: 0 for bucket in HTTP_DURATION_BUCKETS_SECONDS}
    )


class HttpRequestMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[HttpRequestMetricKey, HttpRequestMetricValue] = {}

    def record(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        normalized_method = (method or "UNKNOWN").upper()
        normalized_route = route or "unknown"
        normalized_status_code = int(status_code)
        normalized_duration = max(float(duration_seconds), 0.0)
        key = HttpRequestMetricKey(
            method=normalized_method,
            route=normalized_route,
            status_code=normalized_status_code,
        )

        with self._lock:
            value = self._requests.setdefault(key, HttpRequestMetricValue())
            value.count += 1
            value.duration_sum_seconds += normalized_duration
            for bucket in HTTP_DURATION_BUCKETS_SECONDS:
                if normalized_duration <= bucket:
                    value.buckets[bucket] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            requests = [
                {
                    "method": key.method,
                    "route": key.route,
                    "status_code": key.status_code,
                    "status_class": _status_class(key.status_code),
                    "count": value.count,
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
                    self._requests.items(),
                    key=lambda item: (
                        item[0].route,
                        item[0].method,
                        item[0].status_code,
                    ),
                )
            ]
        return {
            "total_count": sum(item["count"] for item in requests),
            "requests": requests,
        }

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()


_http_request_metrics = HttpRequestMetrics()


def record_http_request(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    _http_request_metrics.record(
        method=method,
        route=route,
        status_code=status_code,
        duration_seconds=duration_seconds,
    )


def get_http_metrics_snapshot() -> dict[str, Any]:
    return _http_request_metrics.snapshot()


def reset_http_metrics() -> None:
    _http_request_metrics.reset()


def _status_class(status_code: int) -> str:
    if status_code < 100:
        return "unknown"
    return f"{status_code // 100}xx"


def _bucket_label(bucket: float) -> str:
    return f"{bucket:g}"
