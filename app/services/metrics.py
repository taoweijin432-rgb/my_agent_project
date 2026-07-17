from collections.abc import Mapping
from datetime import datetime, timezone
from importlib import import_module
from typing import Any

from app.core.config import Settings
from app.services.http_metrics import get_http_metrics_snapshot
from app.services.llm_metrics import get_llm_metrics_snapshot
from app.services.readiness import build_readiness_report
from app.services.stage_metrics import get_stage_metrics_snapshot
from app.services.stores import (
    GenerationHistoryRepository,
    GenerationJobRepository,
    TestAgentWorkflowJobRepository,
    TestPlanExecutionJobRepository,
    create_generation_history_store,
    create_generation_job_store,
    create_test_agent_workflow_job_store,
    create_test_plan_execution_job_store,
)


JOB_STATUSES = ("queued", "running", "succeeded", "failed")
GENERATION_RECORD_STATUSES = ("success", "failed")
GATE_STATUSES = ("pending", "approved", "rejected")
RQ_REGISTRIES = ("queued", "started", "deferred", "scheduled", "failed", "finished")


def build_metrics_snapshot(
    settings: Settings,
    *,
    generation_history_store: GenerationHistoryRepository | None = None,
    generation_store: GenerationJobRepository | None = None,
    test_plan_execution_store: TestPlanExecutionJobRepository | None = None,
    test_agent_workflow_store: TestAgentWorkflowJobRepository | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = now or datetime.now(timezone.utc)
    effective_generation_store = generation_store or create_generation_job_store(settings)
    readiness = build_readiness_report(settings, job_store=effective_generation_store)
    jobs = {
        "generation": _job_store_metrics(
            effective_generation_store
        ),
        "test_plan_execution": _job_store_metrics(
            test_plan_execution_store or create_test_plan_execution_job_store(settings)
        ),
        "test_agent_workflow": _job_store_metrics(
            test_agent_workflow_store or create_test_agent_workflow_job_store(settings)
        ),
    }
    return {
        "generated_at": observed_at.isoformat(),
        "service": settings.app_name,
        "environment": settings.app_env,
        "ready": bool(readiness.get("ready")),
        "database": {"backend": settings.database_backend},
        "queue": _queue_metrics(settings),
        "llm": {
            "configured": bool(settings.zhipu_api_key),
            "model": settings.zhipu_chat_model,
            "timeout_seconds": settings.llm_timeout_seconds,
            "max_retries": settings.llm_max_retries,
            "retry_backoff_seconds": settings.llm_retry_backoff_seconds,
            "runtime": get_llm_metrics_snapshot(),
        },
        "http": get_http_metrics_snapshot(),
        "history": _safe_history_metrics(settings, generation_history_store),
        "jobs": jobs,
        "stages": get_stage_metrics_snapshot(),
        "readiness": _readiness_metrics(readiness),
    }


def format_prometheus_metrics(snapshot: Mapping[str, Any]) -> str:
    lines = [
        "# HELP ai_testcase_ready Service readiness, 1 when ready.",
        "# TYPE ai_testcase_ready gauge",
        f"ai_testcase_ready {_bool_metric(snapshot.get('ready'))}",
        "# HELP ai_testcase_llm_configured LLM API key configuration, 1 when configured.",
        "# TYPE ai_testcase_llm_configured gauge",
        _metric_line(
            "ai_testcase_llm_configured",
            _bool_metric((snapshot.get("llm") or {}).get("configured")),
            {"model": str((snapshot.get("llm") or {}).get("model") or "")},
        ),
        "# HELP ai_testcase_llm_timeout_seconds Configured LLM timeout in seconds.",
        "# TYPE ai_testcase_llm_timeout_seconds gauge",
        f"ai_testcase_llm_timeout_seconds {_number((snapshot.get('llm') or {}).get('timeout_seconds'))}",
        "# HELP ai_testcase_llm_max_retries Configured LLM retry count.",
        "# TYPE ai_testcase_llm_max_retries gauge",
        f"ai_testcase_llm_max_retries {_number((snapshot.get('llm') or {}).get('max_retries'))}",
        "# HELP ai_testcase_job_count Job count by queue and status.",
        "# TYPE ai_testcase_job_count gauge",
    ]

    llm = snapshot.get("llm") or {}
    runtime = llm.get("runtime") if isinstance(llm, Mapping) else None
    if isinstance(runtime, Mapping):
        _append_llm_runtime_metrics(lines, runtime)

    stages = snapshot.get("stages") or {}
    if isinstance(stages, Mapping):
        _append_stage_metrics(lines, stages)

    jobs = snapshot.get("jobs") or {}
    if isinstance(jobs, Mapping):
        for queue_name, metrics in sorted(jobs.items()):
            if not isinstance(metrics, Mapping):
                continue
            status_counts = metrics.get("by_status") or {}
            if not isinstance(status_counts, Mapping):
                continue
            for status, count in sorted(status_counts.items()):
                lines.append(
                    _metric_line(
                        "ai_testcase_job_count",
                        _number(count),
                        {"queue": str(queue_name), "status": str(status)},
                    )
                )
            lines.append(
                _metric_line(
                    "ai_testcase_job_active_count",
                    _number(metrics.get("active_count")),
                    {"queue": str(queue_name)},
                )
            )

    history = snapshot.get("history") or {}
    if isinstance(history, Mapping):
        generation_records = history.get("generation_records") or {}
        record_counts = (
            generation_records.get("by_status")
            if isinstance(generation_records, Mapping)
            else None
        )
        if isinstance(record_counts, Mapping):
            lines.extend(
                [
                    "# HELP ai_testcase_generation_record_count Generation history record count by status.",
                    "# TYPE ai_testcase_generation_record_count gauge",
                ]
            )
            for status, count in sorted(record_counts.items()):
                lines.append(
                    _metric_line(
                        "ai_testcase_generation_record_count",
                        _number(count),
                        {"status": str(status)},
                    )
                )
        generation_gates = history.get("generation_gates") or {}
        gate_counts = (
            generation_gates.get("by_status")
            if isinstance(generation_gates, Mapping)
            else None
        )
        if isinstance(gate_counts, Mapping):
            lines.extend(
                [
                    "# HELP ai_testcase_generation_gate_count Generation gate record count by resolution status.",
                    "# TYPE ai_testcase_generation_gate_count gauge",
                ]
            )
            for status, count in sorted(gate_counts.items()):
                lines.append(
                    _metric_line(
                        "ai_testcase_generation_gate_count",
                        _number(count),
                        {"status": str(status)},
                    )
                )
        usage = history.get("usage") or {}
        if isinstance(usage, Mapping):
            _append_generation_usage_metrics(lines, usage)

    queue = snapshot.get("queue") or {}
    if isinstance(queue, Mapping):
        lines.extend(
            [
                "# HELP ai_testcase_rq_registry_jobs Redis/RQ registry job counts.",
                "# TYPE ai_testcase_rq_registry_jobs gauge",
            ]
        )
        registries = queue.get("registries") or {}
        if isinstance(registries, Mapping):
            for registry, count in sorted(registries.items()):
                lines.append(
                    _metric_line(
                        "ai_testcase_rq_registry_jobs",
                        _number(count),
                        {"registry": str(registry)},
                    )
                )
        lines.append("# HELP ai_testcase_rq_worker_count Redis/RQ worker count.")
        lines.append("# TYPE ai_testcase_rq_worker_count gauge")
        lines.append(f"ai_testcase_rq_worker_count {_number(queue.get('worker_count'))}")

    readiness = snapshot.get("readiness") or {}
    checks = readiness.get("checks") if isinstance(readiness, Mapping) else None
    if isinstance(checks, list):
        lines.extend(
            [
                "# HELP ai_testcase_readiness_check_status Readiness check status, 1 for ok, 0.5 for warn, 0 for error.",
                "# TYPE ai_testcase_readiness_check_status gauge",
            ]
        )
        for check in checks:
            if not isinstance(check, Mapping):
                continue
            lines.append(
                _metric_line(
                    "ai_testcase_readiness_check_status",
                    _readiness_status_value(str(check.get("status") or "")),
                    {"name": str(check.get("name") or "")},
                )
            )
    http_metrics = snapshot.get("http") or {}
    requests = (
        http_metrics.get("requests")
        if isinstance(http_metrics, Mapping)
        else None
    )
    if isinstance(requests, list):
        lines.extend(
            [
                "# HELP ai_testcase_http_requests_total HTTP request count by route, method and status.",
                "# TYPE ai_testcase_http_requests_total counter",
                "# HELP ai_testcase_http_request_duration_seconds HTTP request duration histogram in seconds.",
                "# TYPE ai_testcase_http_request_duration_seconds histogram",
            ]
        )
        for item in requests:
            if not isinstance(item, Mapping):
                continue
            labels = _http_labels(item)
            count = _number(item.get("count"))
            lines.append(_metric_line("ai_testcase_http_requests_total", count, labels))
            duration = item.get("duration_seconds") or {}
            buckets = duration.get("buckets") if isinstance(duration, Mapping) else None
            if isinstance(buckets, Mapping):
                for le, bucket_count in sorted(
                    buckets.items(),
                    key=lambda bucket: _bucket_sort_key(str(bucket[0])),
                ):
                    lines.append(
                        _metric_line(
                            "ai_testcase_http_request_duration_seconds_bucket",
                            _number(bucket_count),
                            {**labels, "le": str(le)},
                        )
                    )
            lines.append(
                _metric_line(
                    "ai_testcase_http_request_duration_seconds_sum",
                    _number(duration.get("sum") if isinstance(duration, Mapping) else None),
                    labels,
                )
            )
            lines.append(
                _metric_line(
                    "ai_testcase_http_request_duration_seconds_count",
                    count,
                    labels,
                )
            )
    return "\n".join(lines) + "\n"


def _job_store_metrics(
    store: GenerationJobRepository
    | TestPlanExecutionJobRepository
    | TestAgentWorkflowJobRepository,
) -> dict[str, Any]:
    counts = store.count_jobs_by_status()
    normalized = {status: int(counts.get(status, 0)) for status in JOB_STATUSES}
    return {
        "active_count": sum(normalized[status] for status in ("queued", "running")),
        "by_status": normalized,
    }


def _append_llm_runtime_metrics(lines: list[str], runtime: Mapping[str, Any]) -> None:
    calls = runtime.get("calls")
    if isinstance(calls, list):
        lines.extend(
            [
                "# HELP ai_testcase_llm_call_total LLM call count by final status and error code.",
                "# TYPE ai_testcase_llm_call_total counter",
                "# HELP ai_testcase_llm_retry_total LLM retry count by final call status and error code.",
                "# TYPE ai_testcase_llm_retry_total counter",
                "# HELP ai_testcase_llm_call_duration_seconds LLM call duration histogram in seconds.",
                "# TYPE ai_testcase_llm_call_duration_seconds histogram",
            ]
        )
        for item in calls:
            if not isinstance(item, Mapping):
                continue
            labels = _llm_labels(item)
            count = _number(item.get("count"))
            lines.append(_metric_line("ai_testcase_llm_call_total", count, labels))
            lines.append(
                _metric_line(
                    "ai_testcase_llm_retry_total",
                    _number(item.get("retry_count")),
                    labels,
                )
            )
            duration = item.get("duration_seconds") or {}
            buckets = duration.get("buckets") if isinstance(duration, Mapping) else None
            if isinstance(buckets, Mapping):
                for le, bucket_count in sorted(
                    buckets.items(),
                    key=lambda bucket: _bucket_sort_key(str(bucket[0])),
                ):
                    lines.append(
                        _metric_line(
                            "ai_testcase_llm_call_duration_seconds_bucket",
                            _number(bucket_count),
                            {**labels, "le": str(le)},
                        )
                    )
            lines.append(
                _metric_line(
                    "ai_testcase_llm_call_duration_seconds_sum",
                    _number(duration.get("sum") if isinstance(duration, Mapping) else None),
                    labels,
                )
            )
            lines.append(
                _metric_line(
                    "ai_testcase_llm_call_duration_seconds_count",
                    count,
                    labels,
                )
            )

    attempts = runtime.get("attempts")
    if isinstance(attempts, list):
        lines.extend(
            [
                "# HELP ai_testcase_llm_attempt_total LLM attempt count by attempt status and error code.",
                "# TYPE ai_testcase_llm_attempt_total counter",
            ]
        )
        for item in attempts:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                _metric_line(
                    "ai_testcase_llm_attempt_total",
                    _number(item.get("count")),
                    _llm_labels(item),
                )
            )


def _append_stage_metrics(lines: list[str], snapshot: Mapping[str, Any]) -> None:
    stages = snapshot.get("stages")
    if not isinstance(stages, list):
        return
    lines.extend(
        [
            "# HELP ai_testcase_stage_total Business workflow stage execution count.",
            "# TYPE ai_testcase_stage_total counter",
            "# HELP ai_testcase_stage_duration_seconds Business workflow stage duration histogram in seconds.",
            "# TYPE ai_testcase_stage_duration_seconds histogram",
        ]
    )
    for item in stages:
        if not isinstance(item, Mapping):
            continue
        labels = _stage_labels(item)
        count = _number(item.get("count"))
        lines.append(_metric_line("ai_testcase_stage_total", count, labels))
        duration = item.get("duration_seconds") or {}
        buckets = duration.get("buckets") if isinstance(duration, Mapping) else None
        if isinstance(buckets, Mapping):
            for le, bucket_count in sorted(
                buckets.items(),
                key=lambda bucket: _bucket_sort_key(str(bucket[0])),
            ):
                lines.append(
                    _metric_line(
                        "ai_testcase_stage_duration_seconds_bucket",
                        _number(bucket_count),
                        {**labels, "le": str(le)},
                    )
                )
        lines.append(
            _metric_line(
                "ai_testcase_stage_duration_seconds_sum",
                _number(duration.get("sum") if isinstance(duration, Mapping) else None),
                labels,
            )
        )
        lines.append(
            _metric_line(
                "ai_testcase_stage_duration_seconds_count",
                count,
                labels,
            )
        )


def _history_metrics(store: GenerationHistoryRepository) -> dict[str, Any]:
    record_counts = _normalized_counts(
        store.count_records_by_status(),
        GENERATION_RECORD_STATUSES,
    )
    gate_counts = _normalized_counts(
        store.count_gate_records_by_status(),
        GATE_STATUSES,
    )
    return {
        "generation_records": {
            "total_count": sum(record_counts.values()),
            "by_status": record_counts,
        },
        "generation_gates": {
            "total_count": sum(gate_counts.values()),
            "pending_count": gate_counts["pending"],
            "by_status": gate_counts,
        },
        "usage": _usage_metrics(store.summarize_usage()),
    }


def _safe_history_metrics(
    settings: Settings,
    store: GenerationHistoryRepository | None,
) -> dict[str, Any]:
    try:
        return _history_metrics(store or create_generation_history_store(settings))
    except Exception as exc:
        record_counts = _normalized_counts({}, GENERATION_RECORD_STATUSES)
        gate_counts = _normalized_counts({}, GATE_STATUSES)
        return {
            "generation_records": {
                "total_count": 0,
                "by_status": record_counts,
            },
            "generation_gates": {
                "total_count": 0,
                "pending_count": 0,
                "by_status": gate_counts,
            },
            "usage": _usage_metrics({}),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _usage_metrics(summary: Mapping[str, Any]) -> dict[str, Any]:
    tokens_by_status = summary.get("tokens_by_status") or {}
    token_items: list[dict[str, Any]] = []
    if isinstance(tokens_by_status, Mapping):
        for status, values in sorted(tokens_by_status.items()):
            if not isinstance(values, Mapping):
                continue
            for token_type in (
                "prompt_tokens_estimate",
                "completion_tokens_estimate",
                "total_tokens_estimate",
            ):
                token_items.append(
                    {
                        "status": str(status),
                        "token_type": token_type,
                        "value": int(_number(values.get(token_type))),
                    }
                )

    cost_items: list[dict[str, Any]] = []
    costs = summary.get("estimated_cost_by_status_currency") or []
    if isinstance(costs, list):
        for item in costs:
            if not isinstance(item, Mapping):
                continue
            cost_items.append(
                {
                    "status": str(item.get("status") or ""),
                    "currency": str(item.get("currency") or "unknown"),
                    "value": float(_number(item.get("estimated_cost"))),
                }
            )
    return {
        "tokens": token_items,
        "estimated_cost": cost_items,
    }


def _append_generation_usage_metrics(lines: list[str], usage: Mapping[str, Any]) -> None:
    tokens = usage.get("tokens")
    if isinstance(tokens, list):
        lines.extend(
            [
                "# HELP ai_testcase_generation_usage_tokens Aggregated generation usage token estimates from history.",
                "# TYPE ai_testcase_generation_usage_tokens gauge",
            ]
        )
        for item in tokens:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                _metric_line(
                    "ai_testcase_generation_usage_tokens",
                    _number(item.get("value")),
                    {
                        "status": str(item.get("status") or ""),
                        "token_type": str(item.get("token_type") or ""),
                    },
                )
            )

    costs = usage.get("estimated_cost")
    if isinstance(costs, list):
        lines.extend(
            [
                "# HELP ai_testcase_generation_estimated_cost Aggregated generation estimated cost from history.",
                "# TYPE ai_testcase_generation_estimated_cost gauge",
            ]
        )
        for item in costs:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                _metric_line(
                    "ai_testcase_generation_estimated_cost",
                    _number(item.get("value")),
                    {
                        "currency": str(item.get("currency") or "unknown"),
                        "status": str(item.get("status") or ""),
                    },
                )
            )


def _normalized_counts(counts: Mapping[str, int], statuses: tuple[str, ...]) -> dict[str, int]:
    return {status: int(counts.get(status, 0)) for status in statuses}


def _readiness_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
    checks = [
        {
            "name": str(check.get("name") or ""),
            "status": str(check.get("status") or ""),
        }
        for check in report.get("checks") or []
        if isinstance(check, Mapping)
    ]
    return {
        "ready": bool(report.get("ready")),
        "check_count": len(checks),
        "error_count": sum(1 for check in checks if check["status"] == "error"),
        "warn_count": sum(1 for check in checks if check["status"] == "warn"),
        "checks": checks,
    }


def _queue_metrics(settings: Settings) -> dict[str, Any]:
    if settings.generation_job_queue_backend != "rq":
        return {
            "backend": settings.generation_job_queue_backend,
            "active": False,
            "worker_count": 0,
            "registries": {name: 0 for name in RQ_REGISTRIES},
        }
    try:
        return _rq_metrics(settings)
    except Exception as exc:
        return {
            "backend": "rq",
            "active": False,
            "name": settings.rq_queue_name,
            "worker_count": 0,
            "registries": {name: 0 for name in RQ_REGISTRIES},
            "error": f"{type(exc).__name__}: {exc}",
        }


def _rq_metrics(settings: Settings) -> dict[str, Any]:
    redis_module = import_module("redis")
    rq_module = import_module("rq")
    registry_module = import_module("rq.registry")
    connection = redis_module.Redis.from_url(settings.redis_url)
    connection.ping()
    queue = rq_module.Queue(settings.rq_queue_name, connection=connection)
    registries = {
        "queued": _count_value(queue),
        "started": _count_value(
            registry_module.StartedJobRegistry(queue.name, connection=connection)
        ),
        "deferred": _count_value(
            registry_module.DeferredJobRegistry(queue.name, connection=connection)
        ),
        "scheduled": _count_value(
            registry_module.ScheduledJobRegistry(queue.name, connection=connection)
        ),
        "failed": _count_value(
            registry_module.FailedJobRegistry(queue.name, connection=connection)
        ),
        "finished": _count_value(
            registry_module.FinishedJobRegistry(queue.name, connection=connection)
        ),
    }
    workers = [
        worker
        for worker in rq_module.Worker.all(connection=connection)
        if queue.name in [worker_queue.name for worker_queue in worker.queues]
    ]
    return {
        "backend": "rq",
        "active": True,
        "name": queue.name,
        "worker_count": len(workers),
        "registries": registries,
    }


def _count_value(value: Any) -> int:
    if hasattr(value, "count"):
        return int(value.count)
    if hasattr(value, "get_job_ids"):
        return len(value.get_job_ids())
    return 0


def _metric_line(name: str, value: int | float, labels: Mapping[str, str]) -> str:
    label_text = ",".join(
        f'{key}="{_escape_label_value(item)}"' for key, item in sorted(labels.items())
    )
    return f"{name}{{{label_text}}} {value}"


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _bool_metric(value: object) -> int:
    return 1 if bool(value) else 0


def _number(value: object) -> int | float:
    if isinstance(value, bool):
        return _bool_metric(value)
    if isinstance(value, int | float):
        return value
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0


def _readiness_status_value(status: str) -> float:
    if status == "ok":
        return 1.0
    if status == "warn":
        return 0.5
    return 0.0


def _http_labels(item: Mapping[str, Any]) -> dict[str, str]:
    return {
        "method": str(item.get("method") or ""),
        "route": str(item.get("route") or ""),
        "status_class": str(item.get("status_class") or ""),
        "status_code": str(item.get("status_code") or ""),
    }


def _llm_labels(item: Mapping[str, Any]) -> dict[str, str]:
    return {
        "model": str(item.get("model") or ""),
        "status": str(item.get("status") or ""),
        "error_code": str(item.get("error_code") or "none"),
    }


def _stage_labels(item: Mapping[str, Any]) -> dict[str, str]:
    return {
        "workflow": str(item.get("workflow") or ""),
        "stage": str(item.get("stage") or ""),
        "status": str(item.get("status") or ""),
    }


def _bucket_sort_key(label: str) -> tuple[int, float | str]:
    if label == "+Inf":
        return (1, label)
    try:
        return (0, float(label))
    except ValueError:
        return (0, label)
