from pathlib import Path

from app.models.test_plan import TestToolType as ToolType
from app.models.test_plan import TestPlan as PlanModel
from app.models.test_plan import ToolRun, ToolRunStatus
from scripts.evaluate_test_report import (
    DEFAULT_CASES_PATH,
    _evidence_artifacts_cover_expected_steps,
    _recommendations_include_next_actions,
    _recommendations_ground_expected_steps,
    _summary_matches_report_facts,
    evaluate_cases,
    load_cases,
    main,
    summarize_results,
)


def test_evaluate_test_report_fixture_passes() -> None:
    cases = load_cases(DEFAULT_CASES_PATH)
    results = evaluate_cases(cases)
    summary = summarize_results(results)

    assert summary["case_pass_rate"] == 1.0
    assert summary["status_match_rate"] == 1.0
    assert summary["summary_fact_quality_rate"] == 1.0
    assert summary["coverage_match_rate"] == 1.0
    assert summary["defect_grounding_rate"] == 1.0
    assert summary["reason_classification_rate"] == 1.0
    assert summary["reason_aware_recommendation_rate"] == 1.0
    assert summary["recommendation_grounding_rate"] == 1.0
    assert summary["next_action_quality_rate"] == 1.0
    assert summary["evidence_artifact_quality_rate"] == 1.0
    assert summary["export_fact_rate"] == 1.0


def test_evaluate_test_report_main_outputs_json(capsys) -> None:
    assert main(["--json", "--fail-under-case-pass-rate", "1.0"]) == 0

    output = capsys.readouterr().out
    assert '"case_pass_rate": 1.0' in output
    assert '"summary_fact_quality_rate": 1.0' in output
    assert '"reason_classification_rate": 1.0' in output
    assert '"reason_aware_recommendation_rate": 1.0' in output
    assert '"recommendation_grounding_rate": 1.0' in output
    assert '"next_action_quality_rate": 1.0' in output
    assert '"evidence_artifact_quality_rate": 1.0' in output
    assert '"export_fact_rate": 1.0' in output
    assert '"results"' in output


def test_report_eval_rejects_recommendations_without_step_grounding() -> None:
    failed_run = ToolRun(
        id="run-1",
        plan_step_id="TP-002",
        tool=ToolType.http,
        status=ToolRunStatus.failed,
    )

    assert (
        _recommendations_ground_expected_steps(
            recommendations=["优先复查 failed 步骤对应的接口响应、断言和业务规则。"],
            tool_runs=[failed_run],
            expected_step_ids=["TP-002"],
        )
        is False
    )


def test_report_eval_rejects_recommendations_without_next_action() -> None:
    failed_run = ToolRun(
        id="run-1",
        plan_step_id="TP-002",
        tool=ToolType.http,
        status=ToolRunStatus.failed,
    )

    assert (
        _recommendations_include_next_actions(
            recommendations=["failed 步骤 TP-002 需要关注。"],
            tool_runs=[failed_run],
            expected_keywords_by_step_id={"TP-002": ["复查", "检查"]},
        )
        is False
    )


def test_report_eval_rejects_missing_evidence_artifact_trace() -> None:
    failed_run = ToolRun(
        id="run-1",
        plan_step_id="TP-002",
        tool=ToolType.http,
        status=ToolRunStatus.failed,
        output_summary="HTTP 500 internal error",
        artifact_paths=["data/test-artifacts/run-1/response.txt"],
    )

    assert (
        _evidence_artifacts_cover_expected_steps(
            markdown="| Step | Status |\n| TP-002 | failed |",
            tool_runs=[failed_run],
            expected_step_ids=["TP-002"],
        )
        is False
    )


def test_report_eval_fails_when_reason_classification_does_not_match() -> None:
    case = load_cases(DEFAULT_CASES_PATH)[0]
    mutated = {
        **case,
        "expected": {
            **case["expected"],
            "reason_classifications": {"TP-002": "http_status_mismatch"},
        },
    }

    result = evaluate_cases([mutated])[0]

    assert result["case_pass"] is False
    assert result["reason_classification_pass"] is False


def test_report_eval_fails_when_recommendation_does_not_match_reason() -> None:
    case = load_cases(DEFAULT_CASES_PATH)[0]
    mutated = {
        **case,
        "expected": {
            **case["expected"],
            "reason_aware_recommendation_keywords_by_step_id": {
                "TP-002": ["冲突", "幂等"],
            },
        },
    }

    result = evaluate_cases([mutated])[0]

    assert result["case_pass"] is False
    assert result["reason_aware_recommendation_pass"] is False


def test_report_eval_rejects_summary_missing_facts() -> None:
    case = load_cases(DEFAULT_CASES_PATH)[0]
    plan = PlanModel.model_validate(case["plan"])
    tool_runs = [ToolRun.model_validate(item) for item in case["tool_runs"]]

    assert (
        _summary_matches_report_facts(
            summary="登录执行计划: executed 2/2 step(s); failed=1.",
            plan=plan,
            tool_runs=tool_runs,
            report_status="failed",
            requirement_coverage={"REQ-001": True, "REQ-002": False},
        )
        is False
    )


def test_load_report_eval_cases_rejects_non_array_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")

    try:
        load_cases(path)
    except ValueError as exc:
        assert "must be a JSON array" in str(exc)
    else:
        raise AssertionError("expected ValueError")
