import threading
from dataclasses import dataclass, field
from typing import Any


STAGE_DURATION_BUCKETS_SECONDS = (
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
    30.0,
    60.0,
    120.0,
)


@dataclass(frozen=True)
class StageMetricKey:
    workflow: str
    stage: str
    status: str


@dataclass
class StageMetricValue:
    count: int = 0
    duration_sum_seconds: float = 0.0
    buckets: dict[float, int] = field(
        default_factory=lambda: {
            bucket: 0 for bucket in STAGE_DURATION_BUCKETS_SECONDS
        }
    )


class StageRuntimeMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stages: dict[StageMetricKey, StageMetricValue] = {}

    def record(
        self,
        *,
        workflow: str,
        stage: str,
        status: str,
        duration_ms: float,
    ) -> None:
        key = StageMetricKey(
            workflow=_label_value(workflow),
            stage=_label_value(stage),
            status=_label_value(status),
        )
        duration_seconds = max(float(duration_ms) / 1000, 0.0)
        with self._lock:
            value = self._stages.setdefault(key, StageMetricValue())
            value.count += 1
            value.duration_sum_seconds += duration_seconds
            for bucket in STAGE_DURATION_BUCKETS_SECONDS:
                if duration_seconds <= bucket:
                    value.buckets[bucket] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            stages = [
                {
                    "workflow": key.workflow,
                    "stage": key.stage,
                    "status": key.status,
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
                    self._stages.items(),
                    key=lambda item: (
                        item[0].workflow,
                        item[0].stage,
                        item[0].status,
                    ),
                )
            ]
        return {
            "total_count": sum(item["count"] for item in stages),
            "stages": stages,
        }

    def reset(self) -> None:
        with self._lock:
            self._stages.clear()


_stage_runtime_metrics = StageRuntimeMetrics()


def record_stage_duration(
    *,
    workflow: str,
    stage: str,
    status: str,
    duration_ms: float,
) -> None:
    _stage_runtime_metrics.record(
        workflow=workflow,
        stage=stage,
        status=status,
        duration_ms=duration_ms,
    )


def get_stage_metrics_snapshot() -> dict[str, Any]:
    return _stage_runtime_metrics.snapshot()


def reset_stage_metrics() -> None:
    _stage_runtime_metrics.reset()


def _label_value(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value or "unknown")


def _bucket_label(bucket: float) -> str:
    return f"{bucket:g}"
