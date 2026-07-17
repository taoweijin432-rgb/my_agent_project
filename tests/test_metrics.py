from datetime import datetime, timezone
from typing import Any

import pytest

from app.core.config import Settings
from app.services.http_metrics import record_http_request, reset_http_metrics
from app.services.llm import LLMCallAttemptMetrics, LLMCallMetrics
from app.services.llm_metrics import record_llm_call, reset_llm_metrics
from app.services.metrics import build_metrics_snapshot, format_prometheus_metrics
from app.services.stage_metrics import (
    get_stage_metrics_snapshot,
    record_stage_duration,
    reset_stage_metrics,
)


class FakeJobStore:
    def __init__(self, counts: dict[str, int]):
        self.counts = counts

    def count_jobs_by_status(self) -> dict[str, int]:
        return dict(self.counts)

    def count_active_jobs(self) -> int:
        return self.counts.get("queued", 0) + self.counts.get("running", 0)


class FakeHistoryStore:
    def __init__(
        self,
        record_counts: dict[str, int] | None = None,
        gate_counts: dict[str, int] | None = None,
        usage_summary: dict[str, Any] | None = None,
    ) -> None:
        self.record_counts = record_counts or {}
        self.gate_counts = gate_counts or {}
        self.usage_summary = usage_summary or {}

    def count_records_by_status(self) -> dict[str, int]:
        return dict(self.record_counts)

    def count_gate_records_by_status(self) -> dict[str, int]:
        return dict(self.gate_counts)

    def summarize_usage(self) -> dict[str, Any]:
        return dict(self.usage_summary)


@pytest.fixture(autouse=True)
def clear_http_metrics() -> None:
    reset_http_metrics()
    reset_llm_metrics()
    reset_stage_metrics()
    yield
    reset_llm_metrics()
    reset_http_metrics()
    reset_stage_metrics()


def test_build_metrics_snapshot_counts_jobs_and_readiness() -> None:
    settings = Settings(app_api_key="service-key", zhipu_api_key="zhipu-key")
    record_http_request(
        method="get",
        route="/health",
        status_code=200,
        duration_seconds=0.012,
    )
    record_llm_call(
        LLMCallMetrics(
            model="glm-test",
            base_url="https://example.test",
            timeout_seconds=3,
            max_retries=1,
            retry_backoff_seconds=0.25,
            attempts=(
                LLMCallAttemptMetrics(
                    attempt=1,
                    duration_ms=12.0,
                    status="failed",
                    error_code="timeout",
                    error_type="ReadTimeout",
                    retryable=True,
                ),
                LLMCallAttemptMetrics(
                    attempt=2,
                    duration_ms=8.0,
                    status="succeeded",
                ),
            ),
        )
    )

    snapshot = build_metrics_snapshot(
        settings,
        generation_history_store=FakeHistoryStore(
            {"success": 5, "failed": 2},
            {"pending": 1, "approved": 2},
            {
                "tokens_by_status": {
                    "success": {
                        "prompt_tokens_estimate": 50,
                        "completion_tokens_estimate": 20,
                        "total_tokens_estimate": 70,
                    },
                    "failed": {
                        "prompt_tokens_estimate": 40,
                        "completion_tokens_estimate": 0,
                        "total_tokens_estimate": 40,
                    },
                },
                "estimated_cost_by_status_currency": [
                    {
                        "status": "success",
                        "currency": "CNY",
                        "estimated_cost": 0.001,
                    }
                ],
            },
        ),
        generation_store=FakeJobStore({"queued": 1, "running": 2, "succeeded": 3}),
        test_plan_execution_store=FakeJobStore({"failed": 1}),
        test_agent_workflow_store=FakeJobStore({"succeeded": 4}),
        now=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert snapshot["ready"] is True
    assert snapshot["generated_at"] == "2026-07-15T00:00:00+00:00"
    assert snapshot["jobs"]["generation"]["active_count"] == 3
    assert snapshot["jobs"]["generation"]["by_status"]["succeeded"] == 3
    assert snapshot["jobs"]["test_plan_execution"]["by_status"]["failed"] == 1
    assert snapshot["jobs"]["test_agent_workflow"]["by_status"]["succeeded"] == 4
    assert snapshot["queue"]["backend"] == "in_memory"
    assert snapshot["queue"]["registries"]["failed"] == 0
    assert snapshot["llm"]["configured"] is True
    assert snapshot["llm"]["runtime"]["call_count"] == 1
    assert snapshot["llm"]["runtime"]["attempt_count"] == 2
    assert snapshot["llm"]["runtime"]["retry_count"] == 1
    assert snapshot["history"]["generation_records"]["total_count"] == 7
    assert snapshot["history"]["generation_records"]["by_status"]["success"] == 5
    assert snapshot["history"]["generation_gates"]["pending_count"] == 1
    assert snapshot["history"]["generation_gates"]["by_status"]["approved"] == 2
    assert {
        (item["status"], item["token_type"], item["value"])
        for item in snapshot["history"]["usage"]["tokens"]
    } == {
        ("success", "prompt_tokens_estimate", 50),
        ("success", "completion_tokens_estimate", 20),
        ("success", "total_tokens_estimate", 70),
        ("failed", "prompt_tokens_estimate", 40),
        ("failed", "completion_tokens_estimate", 0),
        ("failed", "total_tokens_estimate", 40),
    }
    assert snapshot["history"]["usage"]["estimated_cost"] == [
        {"status": "success", "currency": "CNY", "value": 0.001}
    ]
    assert snapshot["http"]["total_count"] == 1
    assert snapshot["http"]["requests"][0]["method"] == "GET"
    assert snapshot["http"]["requests"][0]["route"] == "/health"
    assert snapshot["http"]["requests"][0]["status_class"] == "2xx"
    assert snapshot["http"]["requests"][0]["duration_seconds"]["buckets"]["0.025"] == 1
    assert snapshot["readiness"]["error_count"] == 0


def test_format_prometheus_metrics_exports_core_series() -> None:
    settings = Settings(app_api_key="service-key", zhipu_api_key="zhipu-key")
    record_http_request(
        method="post",
        route="/api/v1/test-cases/generate",
        status_code=503,
        duration_seconds=0.31,
    )
    record_llm_call(
        LLMCallMetrics(
            model="glm-test",
            base_url="https://example.test",
            timeout_seconds=3,
            max_retries=1,
            retry_backoff_seconds=0.25,
            attempts=(
                LLMCallAttemptMetrics(
                    attempt=1,
                    duration_ms=120.0,
                    status="failed",
                    error_code="rate_limited",
                    error_type="HTTPStatusError",
                    retryable=True,
                ),
                LLMCallAttemptMetrics(
                    attempt=2,
                    duration_ms=90.0,
                    status="succeeded",
                ),
            ),
        )
    )
    snapshot = build_metrics_snapshot(
        settings,
        generation_history_store=FakeHistoryStore(
            {"success": 8, "failed": 3},
            {"pending": 2, "rejected": 1},
            {
                "tokens_by_status": {
                    "success": {
                        "prompt_tokens_estimate": 800,
                        "completion_tokens_estimate": 300,
                        "total_tokens_estimate": 1100,
                    }
                },
                "estimated_cost_by_status_currency": [
                    {
                        "status": "success",
                        "currency": "CNY",
                        "estimated_cost": 0.12,
                    }
                ],
            },
        ),
        generation_store=FakeJobStore({"queued": 1}),
        test_plan_execution_store=FakeJobStore({}),
        test_agent_workflow_store=FakeJobStore({}),
    )

    output = format_prometheus_metrics(snapshot)

    assert "ai_testcase_ready 1" in output
    assert 'ai_testcase_llm_configured{model="glm-4-flash"} 1' in output
    assert (
        'ai_testcase_llm_call_total{error_code="none",model="glm-test",'
        'status="succeeded"} 1'
    ) in output
    assert (
        'ai_testcase_llm_attempt_total{error_code="rate_limited",model="glm-test",'
        'status="failed"} 1'
    ) in output
    assert (
        'ai_testcase_llm_retry_total{error_code="none",model="glm-test",'
        'status="succeeded"} 1'
    ) in output
    assert (
        'ai_testcase_llm_call_duration_seconds_count{error_code="none",'
        'model="glm-test",status="succeeded"} 1'
    ) in output
    assert 'ai_testcase_job_count{queue="generation",status="queued"} 1' in output
    assert 'ai_testcase_job_active_count{queue="generation"} 1' in output
    assert 'ai_testcase_generation_record_count{status="success"} 8' in output
    assert 'ai_testcase_generation_record_count{status="failed"} 3' in output
    assert 'ai_testcase_generation_gate_count{status="pending"} 2' in output
    assert 'ai_testcase_generation_gate_count{status="rejected"} 1' in output
    assert (
        'ai_testcase_generation_usage_tokens{status="success",'
        'token_type="total_tokens_estimate"} 1100'
    ) in output
    assert (
        'ai_testcase_generation_estimated_cost{currency="CNY",status="success"} 0.12'
    ) in output
    assert "ai_testcase_rq_worker_count 0" in output
    assert 'ai_testcase_readiness_check_status{name="configuration"} 1.0' in output
    assert (
        'ai_testcase_http_requests_total{method="POST",'
        'route="/api/v1/test-cases/generate",status_class="5xx",status_code="503"} 1'
    ) in output
    assert (
        'ai_testcase_http_request_duration_seconds_bucket{le="+Inf",method="POST",'
        'route="/api/v1/test-cases/generate",status_class="5xx",status_code="503"} 1'
    ) in output
    assert (
        'ai_testcase_http_request_duration_seconds_count{method="POST",'
        'route="/api/v1/test-cases/generate",status_class="5xx",status_code="503"} 1'
    ) in output


def test_prometheus_label_values_are_escaped() -> None:
    snapshot: dict[str, Any] = {
        "ready": True,
        "llm": {"configured": True, "model": 'glm"x'},
        "history": {},
        "jobs": {},
        "queue": {"registries": {}, "worker_count": 0},
        "readiness": {"checks": []},
    }

    output = format_prometheus_metrics(snapshot)

    assert 'model="glm\\"x"' in output


def test_stage_metrics_snapshot_and_prometheus_export() -> None:
    record_stage_duration(
        workflow="test_agent_workflow",
        stage="plan_generation",
        status="succeeded",
        duration_ms=12.5,
    )
    record_stage_duration(
        workflow="test_agent_workflow",
        stage="tool_execution",
        status="failed",
        duration_ms=250.0,
    )

    snapshot = get_stage_metrics_snapshot()

    assert snapshot["total_count"] == 2
    assert snapshot["stages"][0]["workflow"] == "test_agent_workflow"
    assert snapshot["stages"][0]["stage"] == "plan_generation"
    assert snapshot["stages"][0]["status"] == "succeeded"
    assert snapshot["stages"][0]["count"] == 1
    assert snapshot["stages"][0]["duration_seconds"]["sum"] == 0.0125
    assert snapshot["stages"][0]["duration_seconds"]["avg"] == 0.0125
    assert snapshot["stages"][0]["duration_seconds"]["buckets"]["0.025"] == 1
    assert snapshot["stages"][0]["duration_seconds"]["buckets"]["+Inf"] == 1

    output = format_prometheus_metrics(
        {
            "ready": True,
            "llm": {"configured": True, "model": "glm-4-flash"},
            "history": {},
            "jobs": {},
            "queue": {"registries": {}, "worker_count": 0},
            "readiness": {"checks": []},
            "stages": snapshot,
        }
    )

    assert "ai_testcase_stage_total" in output
    assert (
        'ai_testcase_stage_total{stage="plan_generation",status="succeeded",'
        'workflow="test_agent_workflow"} 1'
    ) in output
    assert (
        'ai_testcase_stage_duration_seconds_bucket{le="0.025",stage="plan_generation",'
        'status="succeeded",workflow="test_agent_workflow"} 1'
    ) in output
    assert (
        'ai_testcase_stage_duration_seconds_count{stage="tool_execution",'
        'status="failed",workflow="test_agent_workflow"} 1'
    ) in output
