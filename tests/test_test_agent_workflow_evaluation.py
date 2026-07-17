import json
from copy import deepcopy
from pathlib import Path

from scripts.evaluate_test_agent_workflow import (
    CachedLLMClient,
    DEFAULT_CASES_PATH,
    _summary_matches_report_facts,
    build_generator,
    evaluate_case,
    evaluate_cases,
    load_cases,
    main,
    select_cases,
    summarize_results,
)
from app.core.config import Settings
from app.models.test_case import RequirementPoint
from app.models.test_case import TestCaseType as CaseType
from app.models.test_plan import TestPlan as PlanModel
from app.models.test_plan import TestPlanGenerationRequest as PlanRequest
from app.models.test_plan import TestPlanScope as PlanScope
from app.models.test_plan import TestPlanStep as PlanStep
from app.models.test_plan import TestToolType as ToolType
from app.models.test_plan import ToolRun as ToolRunModel
from app.models.test_plan import ToolRunStatus
from app.services.llm import LLMCallAttemptMetrics, LLMCallMetrics
from app.services.test_plan_generator import LLMTestPlanGenerator
from app.services.test_plan_generator import TestPlanGenerator, generate_test_plan


def test_workflow_eval_fixture_passes() -> None:
    cases = load_cases(DEFAULT_CASES_PATH)
    results = evaluate_cases(cases, generator=TestPlanGenerator())
    summary = summarize_results(results)

    assert {case["id"] for case in cases} == {
        "refund-requirements-to-report-001",
        "auth-permission-workflow-001",
        "async-queue-workflow-001",
        "payment-reconciliation-workflow-001",
        "inventory-reservation-workflow-001",
        "notification-retry-workflow-001",
        "file-export-permission-workflow-001",
        "profile-validation-workflow-001",
        "refund-amount-mismatch-workflow-001",
        "async-final-state-workflow-001",
        "checkout-prerequisite-workflow-001",
        "payment-callback-idempotency-workflow-001",
        "pytest-assertion-workflow-001",
        "sql-adapter-missing-workflow-001",
        "manual-confirmation-workflow-001",
    }
    assert summary["case_pass_rate"] == 1.0
    assert summary["tool_args_schema_rate"] == 1.0
    assert summary["plan_tool_hit_rate"] == 1.0
    assert summary["plan_test_type_hit_rate"] == 1.0
    assert summary["plan_step_count_rate"] == 1.0
    assert summary["risk_keyword_hit_rate"] == 1.0
    assert summary["report_status_rate"] == 1.0
    assert summary["summary_fact_quality_rate"] == 1.0
    assert summary["tool_status_rate"] == 1.0
    assert summary["coverage_match_rate"] == 1.0
    assert summary["defect_grounding_rate"] == 1.0
    assert summary["reason_classification_rate"] == 1.0
    assert summary["reason_aware_recommendation_rate"] == 1.0
    assert summary["recommendation_grounding_rate"] == 1.0
    assert summary["next_action_quality_rate"] == 1.0
    assert summary["evidence_artifact_quality_rate"] == 1.0
    assert summary["evidence_rate"] == 1.0
    assert summary["failure_code_counts"] == {}
    assert summary["timing_ms"]["plan_generation"]["count"] == len(cases)
    assert summary["timing_ms"]["total"]["max"] is not None
    assert all("timing_ms" in result for result in results)


def test_workflow_eval_strict_mode_passes_rule_based_fixture() -> None:
    cases = load_cases(DEFAULT_CASES_PATH)
    results = evaluate_cases(
        cases,
        generator=TestPlanGenerator(),
        strict_plan_tools=True,
        strict_plan_test_types=True,
        strict_http_headers=True,
    )
    summary = summarize_results(results)

    assert summary["case_pass_rate"] == 1.0
    assert summary["http_header_value_rate"] == 1.0
    assert summary["strict_modes"] == {
        "plan_tools": True,
        "plan_test_types": True,
        "http_headers": True,
    }


def test_workflow_eval_strict_headers_detect_invalid_values() -> None:
    class InvalidHeaderGenerator:
        def generate(self, request: PlanRequest) -> PlanModel:
            return PlanModel(
                id="plan-invalid-header",
                title="invalid header plan",
                requirements=request.requirements,
                scope=PlanScope(risks=["资金相关路径需要覆盖异常和审计"]),
                steps=[
                    PlanStep(
                        id="TP-001",
                        title="创建退款",
                        objective="创建退款",
                        requirement_ids=["REQ-WORKFLOW-REFUND-001"],
                        test_types=[CaseType.functional],
                        tool=ToolType.http,
                        tool_args={
                            "method": "POST",
                            "path": "/api/v1/refunds",
                            "expected_status": 201,
                            "headers": {"Accept": "application/"},
                        },
                    ),
                    PlanStep(
                        id="TP-002",
                        title="查询退款审计",
                        objective="查询退款审计",
                        requirement_ids=["REQ-WORKFLOW-REFUND-002"],
                        test_types=[CaseType.functional, CaseType.exception],
                        tool=ToolType.http,
                        tool_args={
                            "method": "GET",
                            "path": "/api/v1/refunds/rf_001/audit",
                            "expected_status": 200,
                        },
                    ),
                ],
            )

    result = evaluate_case(
        load_cases(DEFAULT_CASES_PATH)[0],
        generator=InvalidHeaderGenerator(),
        strict_http_headers=True,
    )

    assert result["case_pass"] is False
    assert result["http_header_value_pass"] is False
    assert result["http_header_value_errors"][0]["header"] == "Accept"
    assert "http_header_value_mismatch" in result["failure_codes"]


def test_workflow_eval_reports_failure_diagnostics() -> None:
    case = deepcopy(load_cases(DEFAULT_CASES_PATH)[0])
    case["expected"]["report_status"] = "passed"

    result = evaluate_case(case, generator=TestPlanGenerator())

    assert result["case_pass"] is False
    assert "report_status_mismatch" in result["failure_codes"]
    assert result["failure_reasons"]


def test_workflow_eval_reports_recommendation_grounding_mismatch() -> None:
    case = deepcopy(load_cases(DEFAULT_CASES_PATH)[0])
    case["expected"]["recommendation_step_ids"] = ["TP-999"]

    result = evaluate_case(case, generator=TestPlanGenerator())

    assert result["case_pass"] is False
    assert result["recommendation_grounding_pass"] is False
    assert "recommendation_grounding_mismatch" in result["failure_codes"]


def test_workflow_eval_reports_reason_classification_mismatch() -> None:
    case = deepcopy(load_cases(DEFAULT_CASES_PATH)[0])
    case["expected"]["reason_classifications"] = {
        "TP-002": "timeout",
    }

    result = evaluate_case(case, generator=TestPlanGenerator())

    assert result["case_pass"] is False
    assert result["reason_classification_pass"] is False
    assert "reason_classification_mismatch" in result["failure_codes"]


def test_workflow_eval_reports_reason_aware_recommendation_mismatch() -> None:
    case = deepcopy(load_cases(DEFAULT_CASES_PATH)[0])
    case["expected"]["reason_aware_recommendation_keywords_by_step_id"] = {
        "TP-002": ["冲突", "幂等"],
    }

    result = evaluate_case(case, generator=TestPlanGenerator())

    assert result["case_pass"] is False
    assert result["reason_aware_recommendation_pass"] is False
    assert "reason_aware_recommendation_mismatch" in result["failure_codes"]


def test_workflow_eval_reports_summary_fact_quality_mismatch() -> None:
    plan = PlanModel(
        id="plan-summary",
        title="summary plan",
        scope=PlanScope(),
        steps=[
            PlanStep(
                id="TP-001",
                title="失败步骤",
                objective="验证失败",
                requirement_ids=["REQ-001"],
                tool=ToolType.http,
            )
        ],
    )
    tool_runs = [
        ToolRunModel(
            id="run-1",
            plan_step_id="TP-001",
            tool=ToolType.http,
            status=ToolRunStatus.failed,
        )
    ]

    assert (
        _summary_matches_report_facts(
            summary="summary plan: executed 1/1 step(s); failed=1.",
            plan=plan,
            tool_runs=tool_runs,
            report_status="failed",
            requirement_coverage={"REQ-001": False},
        )
        is False
    )


def test_workflow_eval_reports_next_action_quality_mismatch() -> None:
    case = deepcopy(load_cases(DEFAULT_CASES_PATH)[0])
    case["expected"]["next_action_keywords_by_step_id"] = {
        "TP-002": ["清理缓存"],
    }

    result = evaluate_case(case, generator=TestPlanGenerator())

    assert result["case_pass"] is False
    assert result["next_action_quality_pass"] is False
    assert "next_action_quality_mismatch" in result["failure_codes"]


def test_workflow_eval_reports_evidence_artifact_quality_mismatch() -> None:
    case = deepcopy(load_cases(DEFAULT_CASES_PATH)[0])
    case["expected"]["evidence_step_ids"] = ["TP-999"]

    result = evaluate_case(case, generator=TestPlanGenerator())

    assert result["case_pass"] is False
    assert result["evidence_artifact_quality_pass"] is False
    assert "evidence_artifact_quality_mismatch" in result["failure_codes"]


def test_workflow_eval_validates_real_generated_tool_args() -> None:
    cases = load_cases(DEFAULT_CASES_PATH)
    results = evaluate_cases(cases, generator=TestPlanGenerator())

    assert results
    assert all(result["tool_args_schema_pass"] is True for result in results)
    assert all(result["tool_arg_errors"] == [] for result in results)


def test_workflow_eval_concurrency_preserves_order() -> None:
    cases = load_cases(DEFAULT_CASES_PATH)
    results = evaluate_cases(cases, generator=TestPlanGenerator(), concurrency=2)

    assert [result["id"] for result in results] == [case["id"] for case in cases]
    assert summarize_results(results)["case_pass_rate"] == 1.0


class ObservableWorkflowLLM:
    def __init__(self) -> None:
        self.settings = Settings(
            zhipu_base_url="https://example.test/v4",
            zhipu_chat_model="test-model",
        )
        self.calls = 0
        self.last_call_metrics = None

    def generate_json(self, _messages: list[dict[str, str]]) -> dict[str, object]:
        self.calls += 1
        self.last_call_metrics = LLMCallMetrics(
            model="test-model",
            base_url="https://example.test/v4",
            timeout_seconds=60,
            max_retries=1,
            retry_backoff_seconds=0,
            attempts=(
                LLMCallAttemptMetrics(
                    attempt=1,
                    duration_ms=10,
                    status="failed",
                    error_code="timeout",
                    error_type="ReadTimeout",
                ),
                LLMCallAttemptMetrics(
                    attempt=2,
                    duration_ms=20,
                    status="succeeded",
                ),
            ),
        )
        return {
            "title": "退款 workflow 测试计划",
            "steps": [
                {
                    "title": "创建退款",
                    "requirement_ids": ["REQ-WORKFLOW-REFUND-001"],
                    "test_types": ["functional"],
                    "tool": "http",
                    "tool_args": {
                        "method": "POST",
                        "path": "/api/v1/refunds",
                        "expected_status": 201,
                    },
                },
                {
                    "title": "查询退款审计",
                    "requirement_ids": ["REQ-WORKFLOW-REFUND-002"],
                    "test_types": ["functional", "exception"],
                    "tool": "http",
                    "tool_args": {
                        "method": "GET",
                        "path": "/api/v1/refunds/rf_001/audit",
                        "expected_status": 200,
                    },
                },
            ],
        }


def test_workflow_eval_summarizes_llm_observability() -> None:
    generator = LLMTestPlanGenerator(ObservableWorkflowLLM(), allow_fallback=False)

    result = evaluate_case(load_cases(DEFAULT_CASES_PATH)[0], generator=generator)
    summary = summarize_results([result])

    assert result["case_pass"] is True
    assert result["llm_observability"]["used_llm"] is True
    assert result["llm_observability"]["used_fallback"] is False
    assert result["llm_observability"]["llm"]["attempt_count"] == 2
    assert summary["llm_observability"]["observed_cases"] == 1
    assert summary["llm_observability"]["attempt_count_total"] == 2
    assert summary["llm_observability"]["retry_count_total"] == 1
    assert summary["llm_observability"]["timeout_count"] == 1
    assert summary["llm_observability"]["error_code_counts"] == {"timeout": 1}
    assert summary["llm_observability"]["total_duration_ms"]["avg"] == 30


def test_workflow_eval_summarizes_llm_cache_status(tmp_path: Path) -> None:
    llm = ObservableWorkflowLLM()
    cached_llm = CachedLLMClient(llm, cache_dir=tmp_path)
    generator = LLMTestPlanGenerator(cached_llm, allow_fallback=False)
    case = load_cases(DEFAULT_CASES_PATH)[0]

    first = evaluate_case(case, generator=generator)
    second = evaluate_case(case, generator=generator)
    summary = summarize_results([first, second])

    assert first["llm_observability"]["cache_status"] == "miss"
    assert second["llm_observability"]["cache_status"] == "hit"
    assert summary["llm_observability"]["observed_cases"] == 2
    assert summary["llm_observability"]["cache_status_counts"] == {
        "hit": 1,
        "miss": 1,
    }
    assert summary["llm_observability"]["attempt_count_total"] == 2
    assert llm.calls == 1


def test_workflow_eval_main_outputs_json(capsys) -> None:
    assert main(["--json", "--concurrency", "2", "--fail-under-case-pass-rate", "1.0"]) == 0

    output = capsys.readouterr().out
    assert '"case_pass_rate": 1.0' in output
    assert '"tool_args_schema_rate": 1.0' in output
    assert '"plan_tool_hit_rate": 1.0' in output
    assert '"plan_test_type_hit_rate": 1.0' in output
    assert '"summary_fact_quality_rate": 1.0' in output
    assert '"reason_classification_rate": 1.0' in output
    assert '"reason_aware_recommendation_rate": 1.0' in output
    assert '"recommendation_grounding_rate": 1.0' in output
    assert '"next_action_quality_rate": 1.0' in output
    assert '"evidence_artifact_quality_rate": 1.0' in output
    assert '"timing_ms"' in output
    assert '"results"' in output


def test_workflow_eval_selects_cases_by_id_and_slice() -> None:
    cases = load_cases(DEFAULT_CASES_PATH)

    selected_by_id = select_cases(
        cases,
        case_ids=[
            "manual-confirmation-workflow-001",
            "refund-requirements-to-report-001",
        ],
    )
    selected_by_slice = select_cases(cases, case_slice="1:3")
    selected_by_id_then_slice = select_cases(
        cases,
        case_ids=[
            "manual-confirmation-workflow-001",
            "refund-requirements-to-report-001",
        ],
        case_slice="1:",
    )

    assert [case["id"] for case in selected_by_id] == [
        "manual-confirmation-workflow-001",
        "refund-requirements-to-report-001",
    ]
    assert [case["id"] for case in selected_by_slice] == [
        "auth-permission-workflow-001",
        "async-queue-workflow-001",
    ]
    assert [case["id"] for case in selected_by_id_then_slice] == [
        "refund-requirements-to-report-001"
    ]


def test_workflow_eval_rejects_unknown_case_id() -> None:
    try:
        select_cases(load_cases(DEFAULT_CASES_PATH), case_ids=["missing-case"])
    except ValueError as exc:
        assert "Unknown case id(s): missing-case" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_workflow_eval_main_outputs_selected_cases(capsys) -> None:
    assert (
        main(
            [
                "--json",
                "--case-id",
                "refund-requirements-to-report-001",
                "--case-id",
                "manual-confirmation-workflow-001",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)

    assert output["summary"]["cases"] == 2
    assert [result["id"] for result in output["results"]] == [
        "refund-requirements-to-report-001",
        "manual-confirmation-workflow-001",
    ]


def test_workflow_eval_case_delay_sleeps_between_serial_cases(monkeypatch) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr("scripts.evaluate_test_agent_workflow.time.sleep", sleep_calls.append)

    results = evaluate_cases(
        load_cases(DEFAULT_CASES_PATH)[:3],
        generator=TestPlanGenerator(),
        case_delay_seconds=0.25,
    )

    assert [result["id"] for result in results] == [
        "refund-requirements-to-report-001",
        "auth-permission-workflow-001",
        "async-queue-workflow-001",
    ]
    assert sleep_calls == [0.25, 0.25]


def test_workflow_eval_case_delay_requires_serial_cli(capsys) -> None:
    try:
        main(["--json", "--concurrency", "2", "--case-delay-seconds", "0.1"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")

    assert "--case-delay-seconds requires --concurrency 1" in capsys.readouterr().err


def test_workflow_eval_main_can_fail_on_latency_threshold(capsys) -> None:
    assert main(["--json", "--fail-over-total-ms", "0.000001"]) == 1

    output = capsys.readouterr().out
    assert '"timing_ms"' in output


def test_workflow_eval_appends_benchmark_history_jsonl(
    capsys,
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "benchmark-history.jsonl"

    assert main(["--json", "--benchmark-history-jsonl", str(history_path)]) == 0

    capsys.readouterr()
    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    raw_record = lines[0].lower()
    assert record["schema_version"] == 1
    assert record["backend"] == "deterministic"
    assert record["case_count"] == 15
    assert record["case_ids"] == []
    assert record["case_slice"] == ""
    assert record["case_delay_seconds"] == 0
    assert record["summary"]["timing_ms"]["total"]["count"] == 15
    assert "api_key" not in raw_record
    assert "zhipu_api_key" not in raw_record


def test_workflow_eval_uses_deterministic_generator_by_default() -> None:
    generator = build_generator(use_llm=False, allow_fallback=False)

    assert isinstance(generator, TestPlanGenerator)


def test_workflow_eval_rejects_non_array_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")

    try:
        load_cases(path)
    except ValueError as exc:
        assert "must be a JSON array" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_rule_based_planner_emits_executable_http_args_for_workflow() -> None:
    plan = generate_test_plan(
        PlanRequest(
            description="退款流程。",
            requirements=[
                RequirementPoint(
                    id="REQ-WF-001",
                    title="创建退款",
                    description="POST /api/v1/refunds 返回 201。",
                    keywords=["POST /api/v1/refunds", "201"],
                    priority="critical",
                )
            ],
        )
    )

    assert plan.steps[0].tool == ToolType.http
    assert plan.steps[0].tool_args == {
        "method": "POST",
        "path": "/api/v1/refunds",
        "expected_status": 201,
    }


class FakeJSONLLM:
    def __init__(self) -> None:
        self.settings = Settings(
            zhipu_base_url="https://example.test/v4",
            zhipu_chat_model="test-model",
        )
        self.calls = 0

    def generate_json(self, messages: list[dict[str, str]]) -> dict[str, int | str]:
        self.calls += 1
        return {"call": self.calls, "message_count": len(messages)}


def test_cached_llm_client_reuses_and_refreshes_real_response(tmp_path: Path) -> None:
    llm = FakeJSONLLM()
    messages = [{"role": "user", "content": "生成测试计划"}]

    cached = CachedLLMClient(llm, cache_dir=tmp_path)
    first = cached.generate_json(messages)
    second = cached.generate_json(messages)

    assert first == {"call": 1, "message_count": 1}
    assert second == first
    assert llm.calls == 1
    assert len(list(tmp_path.glob("*.json"))) == 1

    refreshed = CachedLLMClient(llm, cache_dir=tmp_path, refresh=True)
    assert refreshed.generate_json(messages) == {"call": 2, "message_count": 1}

    reused = CachedLLMClient(llm, cache_dir=tmp_path)
    assert reused.generate_json(messages) == {"call": 2, "message_count": 1}
    assert llm.calls == 2
