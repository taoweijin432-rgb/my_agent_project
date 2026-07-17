import argparse
import json
import sys
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.models.test_plan import TestPlan, ToolRun
from app.services.test_report import build_execution_report, export_execution_report


DEFAULT_CASES_PATH = project_root / "tests" / "fixtures" / "test_report_eval_cases.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate test execution report consistency.")
    parser.add_argument(
        "--cases",
        default=str(DEFAULT_CASES_PATH),
        help="Test report eval cases JSON.",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    parser.add_argument("--fail-under-case-pass-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-status-match-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-summary-fact-quality-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-coverage-match-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-defect-grounding-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-reason-classification-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-reason-aware-recommendation-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-recommendation-grounding-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-next-action-quality-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-evidence-artifact-quality-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-export-fact-rate", type=float, default=0.0)
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.cases))
    results = evaluate_cases(cases)
    summary = summarize_results(results)

    if args.json:
        print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
    else:
        print_summary(summary, results)

    if _below_thresholds(summary, args):
        return 1
    return 0


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list):
        raise ValueError("Test report eval cases must be a JSON array.")
    return cases


def evaluate_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [evaluate_case(case) for case in cases]


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    plan = TestPlan.model_validate(case["plan"])
    tool_runs = [ToolRun.model_validate(item) for item in case.get("tool_runs", [])]
    report = build_execution_report(plan, tool_runs)
    markdown = export_execution_report(report, "markdown")
    exported_json = json.loads(export_execution_report(report, "json"))
    expected = case.get("expected") or {}

    status_pass = report.status.value == str(expected.get("status", ""))
    summary_fact_pass = _summary_matches_report_facts(
        summary=report.summary,
        plan=plan,
        tool_runs=tool_runs,
        report_status=report.status.value,
        requirement_coverage=report.requirement_coverage,
    )
    coverage_pass = _coverage_matches(report.requirement_coverage, expected)
    defect_pass = _defects_match_expected_failed_steps(
        defects=report.defects,
        tool_runs=tool_runs,
        expected_step_ids=[str(value) for value in expected.get("defect_step_ids", [])],
    )
    expected_reason_classifications = {
        str(step_id): str(reason)
        for step_id, reason in (
            expected.get(
                "reason_classifications",
                _default_expected_reason_classifications(tool_runs),
            )
            or {}
        ).items()
    }
    reason_classification_pass = (
        report.reason_classifications == expected_reason_classifications
    )
    recommendation_step_ids = [
        str(value)
        for value in expected.get(
            "recommendation_step_ids",
            _default_recommendation_step_ids(tool_runs),
        )
    ]
    recommendation_pass = _recommendations_ground_expected_steps(
        recommendations=report.recommendations,
        tool_runs=tool_runs,
        expected_step_ids=recommendation_step_ids,
    )
    reason_aware_keywords_by_step_id = _reason_aware_keywords_by_step_id(
        expected=expected,
        reason_classifications=expected_reason_classifications,
    )
    reason_aware_recommendation_pass = _recommendations_include_reason_aware_keywords(
        recommendations=report.recommendations,
        expected_keywords_by_step_id=reason_aware_keywords_by_step_id,
    )
    next_action_keywords_by_step_id = _next_action_keywords_by_step_id(
        expected=expected,
        tool_runs=tool_runs,
    )
    next_action_pass = _recommendations_include_next_actions(
        recommendations=report.recommendations,
        tool_runs=tool_runs,
        expected_keywords_by_step_id=next_action_keywords_by_step_id,
    )
    evidence_step_ids = [
        str(value)
        for value in expected.get(
            "evidence_step_ids",
            _default_evidence_step_ids(tool_runs),
        )
    ]
    evidence_artifact_pass = _evidence_artifacts_cover_expected_steps(
        markdown=markdown,
        tool_runs=tool_runs,
        expected_step_ids=evidence_step_ids,
    )
    export_pass = _export_matches_expected_facts(
        markdown=markdown,
        exported_json=exported_json,
        report_id=report.id,
        expected=expected,
    )

    return {
        "id": str(case.get("id", "")),
        "description": str(case.get("description", "")),
        "case_pass": (
            status_pass
            and summary_fact_pass
            and coverage_pass
            and defect_pass
            and reason_classification_pass
            and reason_aware_recommendation_pass
            and recommendation_pass
            and next_action_pass
            and evidence_artifact_pass
            and export_pass
        ),
        "status_pass": status_pass,
        "summary_fact_quality_pass": summary_fact_pass,
        "coverage_pass": coverage_pass,
        "defect_grounding_pass": defect_pass,
        "reason_classification_pass": reason_classification_pass,
        "reason_aware_recommendation_pass": reason_aware_recommendation_pass,
        "recommendation_grounding_pass": recommendation_pass,
        "next_action_quality_pass": next_action_pass,
        "evidence_artifact_quality_pass": evidence_artifact_pass,
        "export_fact_pass": export_pass,
        "expected_status": str(expected.get("status", "")),
        "actual_status": report.status.value,
        "expected_covered_requirement_ids": [
            str(value) for value in expected.get("covered_requirement_ids", [])
        ],
        "expected_uncovered_requirement_ids": [
            str(value) for value in expected.get("uncovered_requirement_ids", [])
        ],
        "actual_requirement_coverage": report.requirement_coverage,
        "expected_defect_step_ids": [
            str(value) for value in expected.get("defect_step_ids", [])
        ],
        "actual_defect_step_ids": _defect_step_ids(report.defects),
        "expected_reason_classifications": expected_reason_classifications,
        "actual_reason_classifications": report.reason_classifications,
        "expected_reason_aware_keywords_by_step_id": reason_aware_keywords_by_step_id,
        "expected_recommendation_step_ids": recommendation_step_ids,
        "expected_next_action_keywords_by_step_id": next_action_keywords_by_step_id,
        "expected_evidence_step_ids": evidence_step_ids,
        "report": {
            "id": report.id,
            "status": report.status.value,
            "summary": report.summary,
            "defects": report.defects,
            "reason_classifications": report.reason_classifications,
            "recommendations": report.recommendations,
        },
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    case_passes = sum(1 for result in results if result["case_pass"])
    status_passes = sum(1 for result in results if result["status_pass"])
    summary_fact_passes = sum(
        1 for result in results if result["summary_fact_quality_pass"]
    )
    coverage_passes = sum(1 for result in results if result["coverage_pass"])
    defect_passes = sum(1 for result in results if result["defect_grounding_pass"])
    reason_classification_passes = sum(
        1 for result in results if result["reason_classification_pass"]
    )
    reason_aware_recommendation_passes = sum(
        1 for result in results if result["reason_aware_recommendation_pass"]
    )
    recommendation_passes = sum(
        1 for result in results if result["recommendation_grounding_pass"]
    )
    next_action_passes = sum(
        1 for result in results if result["next_action_quality_pass"]
    )
    evidence_artifact_passes = sum(
        1 for result in results if result["evidence_artifact_quality_pass"]
    )
    export_passes = sum(1 for result in results if result["export_fact_pass"])
    return {
        "cases": total,
        "case_passes": case_passes,
        "case_pass_rate": _ratio(case_passes, total),
        "status_matches": status_passes,
        "status_match_rate": _ratio(status_passes, total),
        "summary_fact_quality_matches": summary_fact_passes,
        "summary_fact_quality_rate": _ratio(summary_fact_passes, total),
        "coverage_matches": coverage_passes,
        "coverage_match_rate": _ratio(coverage_passes, total),
        "defect_grounding_matches": defect_passes,
        "defect_grounding_rate": _ratio(defect_passes, total),
        "reason_classification_matches": reason_classification_passes,
        "reason_classification_rate": _ratio(reason_classification_passes, total),
        "reason_aware_recommendation_matches": reason_aware_recommendation_passes,
        "reason_aware_recommendation_rate": _ratio(
            reason_aware_recommendation_passes,
            total,
        ),
        "recommendation_grounding_matches": recommendation_passes,
        "recommendation_grounding_rate": _ratio(recommendation_passes, total),
        "next_action_quality_matches": next_action_passes,
        "next_action_quality_rate": _ratio(next_action_passes, total),
        "evidence_artifact_quality_matches": evidence_artifact_passes,
        "evidence_artifact_quality_rate": _ratio(evidence_artifact_passes, total),
        "export_fact_matches": export_passes,
        "export_fact_rate": _ratio(export_passes, total),
    }


def print_summary(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    print("Test execution report evaluation")
    print(f"Cases: {summary['cases']}")
    print(
        "Case pass rate: "
        f"{summary['case_passes']}/{summary['cases']} = {summary['case_pass_rate']}"
    )
    print(
        "Status match rate: "
        f"{summary['status_matches']}/{summary['cases']} = {summary['status_match_rate']}"
    )
    print(
        "Summary fact quality rate: "
        f"{summary['summary_fact_quality_matches']}/{summary['cases']} = "
        f"{summary['summary_fact_quality_rate']}"
    )
    print(
        "Coverage match rate: "
        f"{summary['coverage_matches']}/{summary['cases']} = "
        f"{summary['coverage_match_rate']}"
    )
    print(
        "Defect grounding rate: "
        f"{summary['defect_grounding_matches']}/{summary['cases']} = "
        f"{summary['defect_grounding_rate']}"
    )
    print(
        "Reason classification rate: "
        f"{summary['reason_classification_matches']}/{summary['cases']} = "
        f"{summary['reason_classification_rate']}"
    )
    print(
        "Reason-aware recommendation rate: "
        f"{summary['reason_aware_recommendation_matches']}/{summary['cases']} = "
        f"{summary['reason_aware_recommendation_rate']}"
    )
    print(
        "Recommendation grounding rate: "
        f"{summary['recommendation_grounding_matches']}/{summary['cases']} = "
        f"{summary['recommendation_grounding_rate']}"
    )
    print(
        "Next action quality rate: "
        f"{summary['next_action_quality_matches']}/{summary['cases']} = "
        f"{summary['next_action_quality_rate']}"
    )
    print(
        "Evidence artifact quality rate: "
        f"{summary['evidence_artifact_quality_matches']}/{summary['cases']} = "
        f"{summary['evidence_artifact_quality_rate']}"
    )
    print(
        "Export fact rate: "
        f"{summary['export_fact_matches']}/{summary['cases']} = "
        f"{summary['export_fact_rate']}"
    )
    for result in results:
        status = "PASS" if result["case_pass"] else "FAIL"
        print(f"- {status} {result['id']}: {result['actual_status']}")


def _coverage_matches(coverage: dict[str, bool], expected: dict[str, Any]) -> bool:
    covered_ids = [str(value) for value in expected.get("covered_requirement_ids", [])]
    uncovered_ids = [str(value) for value in expected.get("uncovered_requirement_ids", [])]
    return all(coverage.get(requirement_id) is True for requirement_id in covered_ids) and all(
        coverage.get(requirement_id) is False for requirement_id in uncovered_ids
    )


def _summary_matches_report_facts(
    *,
    summary: str,
    plan: TestPlan,
    tool_runs: list[ToolRun],
    report_status: str,
    requirement_coverage: dict[str, bool],
) -> bool:
    status_counts: dict[str, int] = {}
    for tool_run in tool_runs:
        status_counts[tool_run.status.value] = status_counts.get(tool_run.status.value, 0) + 1
    covered_count = sum(1 for covered in requirement_coverage.values() if covered)
    required_fragments = [
        f"status={report_status}",
        f"executed {len(tool_runs)}/{len(plan.steps)} step(s)",
        f"coverage={covered_count}/{len(requirement_coverage)} requirement(s)",
        f"passed={status_counts.get('passed', 0)}",
        f"failed={status_counts.get('failed', 0)}",
        f"blocked={status_counts.get('blocked', 0)}",
        f"skipped={status_counts.get('skipped', 0)}",
    ]
    return all(fragment in summary for fragment in required_fragments)


def _defects_match_expected_failed_steps(
    *,
    defects: list[str],
    tool_runs: list[ToolRun],
    expected_step_ids: list[str],
) -> bool:
    actual_step_ids = _defect_step_ids(defects)
    failed_step_ids = {
        tool_run.plan_step_id
        for tool_run in tool_runs
        if tool_run.status.value == "failed"
    }
    return set(actual_step_ids) == set(expected_step_ids) and set(actual_step_ids).issubset(
        failed_step_ids
    )


def _default_expected_reason_classifications(tool_runs: list[ToolRun]) -> dict[str, str]:
    defaults: dict[str, str] = {}
    for tool_run in tool_runs:
        if tool_run.status.value == "failed":
            defaults[tool_run.plan_step_id] = "tool_execution_error"
        elif tool_run.status.value == "blocked":
            defaults[tool_run.plan_step_id] = "blocked_environment"
        elif tool_run.status.value == "skipped":
            defaults[tool_run.plan_step_id] = "skipped_not_executed"
    return defaults


def _recommendations_ground_expected_steps(
    *,
    recommendations: list[str],
    tool_runs: list[ToolRun],
    expected_step_ids: list[str],
) -> bool:
    if not expected_step_ids:
        return True
    recommendation_text = "\n".join(recommendations)
    actionable_step_ids = set(_default_recommendation_step_ids(tool_runs))
    return all(step_id in recommendation_text for step_id in expected_step_ids) and set(
        expected_step_ids
    ).issubset(actionable_step_ids)


def _reason_aware_keywords_by_step_id(
    *,
    expected: dict[str, Any],
    reason_classifications: dict[str, str],
) -> dict[str, list[str]]:
    configured = expected.get("reason_aware_recommendation_keywords_by_step_id")
    if isinstance(configured, dict):
        return {
            str(step_id): [str(keyword) for keyword in keywords]
            for step_id, keywords in configured.items()
            if isinstance(keywords, list)
        }
    defaults = {
        "timeout": ["超时", "重试"],
        "conflict": ["幂等", "冲突"],
        "permission_denied": ["权限", "身份"],
        "permission_not_enforced": ["权限校验", "越权"],
        "upstream_unavailable": ["上游", "依赖"],
        "auth_failure": ["认证", "token"],
        "validation_error": ["参数", "校验"],
        "response_assertion_mismatch": ["响应字段", "JSON 断言"],
        "adapter_missing": ["adapter", "启用"],
        "manual_confirmation_required": ["人工", "确认"],
        "assertion_mismatch": ["断言", "业务规则"],
    }
    return {
        step_id: defaults[reason]
        for step_id, reason in reason_classifications.items()
        if reason in defaults
    }


def _recommendations_include_reason_aware_keywords(
    *,
    recommendations: list[str],
    expected_keywords_by_step_id: dict[str, list[str]],
) -> bool:
    for step_id, keywords in expected_keywords_by_step_id.items():
        matching_recommendations = [
            recommendation for recommendation in recommendations if step_id in recommendation
        ]
        if not keywords or not any(
            all(keyword in recommendation for keyword in keywords)
            for recommendation in matching_recommendations
        ):
            return False
    return True


def _default_recommendation_step_ids(tool_runs: list[ToolRun]) -> list[str]:
    return [
        tool_run.plan_step_id
        for tool_run in tool_runs
        if tool_run.status.value in {"failed", "blocked", "skipped"}
    ]


def _next_action_keywords_by_step_id(
    *,
    expected: dict[str, Any],
    tool_runs: list[ToolRun],
) -> dict[str, list[str]]:
    configured = expected.get("next_action_keywords_by_step_id")
    if isinstance(configured, dict):
        return {
            str(step_id): [str(keyword) for keyword in keywords]
            for step_id, keywords in configured.items()
            if isinstance(keywords, list)
        }
    return _default_next_action_keywords_by_step_id(tool_runs)


def _default_next_action_keywords_by_step_id(
    tool_runs: list[ToolRun],
) -> dict[str, list[str]]:
    defaults = {
        "failed": ["复查", "检查", "定位", "修复"],
        "blocked": ["处理", "配置", "修复", "恢复"],
        "skipped": ["确认", "补", "补充"],
    }
    return {
        tool_run.plan_step_id: defaults[tool_run.status.value]
        for tool_run in tool_runs
        if tool_run.status.value in defaults
    }


def _recommendations_include_next_actions(
    *,
    recommendations: list[str],
    tool_runs: list[ToolRun],
    expected_keywords_by_step_id: dict[str, list[str]],
) -> bool:
    if not expected_keywords_by_step_id:
        return True
    actionable_step_ids = set(_default_recommendation_step_ids(tool_runs))
    if not set(expected_keywords_by_step_id).issubset(actionable_step_ids):
        return False
    for step_id, keywords in expected_keywords_by_step_id.items():
        if not keywords:
            return False
        matching_recommendations = [
            recommendation for recommendation in recommendations if step_id in recommendation
        ]
        if not any(
            any(keyword in recommendation for keyword in keywords)
            for recommendation in matching_recommendations
        ):
            return False
    return True


def _default_evidence_step_ids(tool_runs: list[ToolRun]) -> list[str]:
    return [
        tool_run.plan_step_id
        for tool_run in tool_runs
        if tool_run.status.value in {"failed", "blocked", "skipped"}
    ]


def _evidence_artifacts_cover_expected_steps(
    *,
    markdown: str,
    tool_runs: list[ToolRun],
    expected_step_ids: list[str],
) -> bool:
    if not expected_step_ids:
        return True
    actionable_runs = {
        tool_run.plan_step_id: tool_run
        for tool_run in tool_runs
        if tool_run.status.value in {"failed", "blocked", "skipped"}
    }
    for step_id in expected_step_ids:
        tool_run = actionable_runs.get(step_id)
        if tool_run is None or step_id not in markdown:
            return False
        evidence_fragments = [
            *tool_run.artifact_paths,
            *([tool_run.output_summary] if tool_run.output_summary else []),
        ]
        if not evidence_fragments or not any(
            fragment in markdown for fragment in evidence_fragments
        ):
            return False
    return True


def _export_matches_expected_facts(
    *,
    markdown: str,
    exported_json: dict[str, Any],
    report_id: str,
    expected: dict[str, Any],
) -> bool:
    required_fragments = [str(value) for value in expected.get("markdown_fragments", [])]
    forbidden_fragments = [str(value) for value in expected.get("forbidden_fragments", [])]
    fragments_pass = all(fragment in markdown for fragment in required_fragments) and not any(
        fragment in markdown for fragment in forbidden_fragments
    )
    json_pass = exported_json.get("id") == report_id
    return fragments_pass and json_pass


def _defect_step_ids(defects: list[str]) -> list[str]:
    return [defect.split(":", 1)[0].strip() for defect in defects if ":" in defect]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


def _below_thresholds(summary: dict[str, Any], args: argparse.Namespace) -> bool:
    return (
        summary["case_pass_rate"] < args.fail_under_case_pass_rate
        or summary["status_match_rate"] < args.fail_under_status_match_rate
        or summary["summary_fact_quality_rate"]
        < args.fail_under_summary_fact_quality_rate
        or summary["coverage_match_rate"] < args.fail_under_coverage_match_rate
        or summary["defect_grounding_rate"] < args.fail_under_defect_grounding_rate
        or summary["reason_classification_rate"]
        < args.fail_under_reason_classification_rate
        or summary["reason_aware_recommendation_rate"]
        < args.fail_under_reason_aware_recommendation_rate
        or summary["recommendation_grounding_rate"]
        < args.fail_under_recommendation_grounding_rate
        or summary["next_action_quality_rate"] < args.fail_under_next_action_quality_rate
        or summary["evidence_artifact_quality_rate"]
        < args.fail_under_evidence_artifact_quality_rate
        or summary["export_fact_rate"] < args.fail_under_export_fact_rate
    )


if __name__ == "__main__":
    raise SystemExit(main())
