import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.models.test_plan import TestPlan, TestToolType, ToolRun
from app.services.test_report import build_execution_report, export_execution_report
from app.services.tool_adapters import HTTPToolAdapter, PytestToolAdapter
from app.services.tool_execution import ToolExecutionService


DEFAULT_CASES_PATH = project_root / "tests" / "fixtures" / "test_execution_eval_cases.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate end-to-end test execution quality.")
    parser.add_argument(
        "--cases",
        default=str(DEFAULT_CASES_PATH),
        help="Test execution eval cases JSON.",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    parser.add_argument("--fail-under-case-pass-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-report-status-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-summary-fact-quality-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-tool-status-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-coverage-match-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-defect-grounding-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-blocked-grounding-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-evidence-rate", type=float, default=0.0)
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
        raise ValueError("Test execution eval cases must be a JSON array.")
    return cases


def evaluate_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [evaluate_case(case) for case in cases]


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    plan = TestPlan.model_validate(case["plan"])
    service = _execution_service_for_case(case)
    tool_runs = service.execute_plan(plan)
    report = build_execution_report(plan, tool_runs)
    markdown = export_execution_report(report, "markdown")
    expected = case.get("expected") or {}

    actual_tool_statuses = {
        tool_run.plan_step_id: tool_run.status.value for tool_run in tool_runs
    }
    expected_tool_statuses = {
        str(step_id): str(status)
        for step_id, status in (expected.get("tool_run_statuses") or {}).items()
    }
    report_status_pass = report.status.value == str(expected.get("report_status", ""))
    summary_fact_pass = _summary_matches_report_facts(
        summary=report.summary,
        plan=plan,
        tool_runs=tool_runs,
        report_status=report.status.value,
        requirement_coverage=report.requirement_coverage,
    )
    tool_status_pass = actual_tool_statuses == expected_tool_statuses
    coverage_pass = _coverage_matches(report.requirement_coverage, expected)
    defect_pass = _defects_match_expected_failed_steps(
        defects=report.defects,
        tool_runs=tool_runs,
        expected_step_ids=[str(value) for value in expected.get("defect_step_ids", [])],
    )
    blocked_pass = _blocked_steps_match_expected(
        tool_runs=tool_runs,
        expected_step_ids=[str(value) for value in expected.get("blocked_step_ids", [])],
    )
    evidence_pass = _evidence_contains_expected_fragments(
        report_markdown=markdown,
        tool_runs=tool_runs,
        expected=expected,
    )

    return {
        "id": str(case.get("id", "")),
        "description": str(case.get("description", "")),
        "case_pass": (
            report_status_pass
            and summary_fact_pass
            and tool_status_pass
            and coverage_pass
            and defect_pass
            and blocked_pass
            and evidence_pass
        ),
        "report_status_pass": report_status_pass,
        "summary_fact_quality_pass": summary_fact_pass,
        "tool_status_pass": tool_status_pass,
        "coverage_pass": coverage_pass,
        "defect_grounding_pass": defect_pass,
        "blocked_grounding_pass": blocked_pass,
        "evidence_pass": evidence_pass,
        "expected_report_status": str(expected.get("report_status", "")),
        "actual_report_status": report.status.value,
        "expected_tool_run_statuses": expected_tool_statuses,
        "actual_tool_run_statuses": actual_tool_statuses,
        "actual_requirement_coverage": report.requirement_coverage,
        "expected_defect_step_ids": [
            str(value) for value in expected.get("defect_step_ids", [])
        ],
        "actual_defect_step_ids": _defect_step_ids(report.defects),
        "expected_blocked_step_ids": [
            str(value) for value in expected.get("blocked_step_ids", [])
        ],
        "actual_blocked_step_ids": _blocked_step_ids(tool_runs),
        "report": {
            "id": report.id,
            "summary": report.summary,
            "defects": report.defects,
            "recommendations": report.recommendations,
        },
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    case_passes = sum(1 for result in results if result["case_pass"])
    report_status_passes = sum(1 for result in results if result["report_status_pass"])
    summary_fact_passes = sum(
        1 for result in results if result["summary_fact_quality_pass"]
    )
    tool_status_passes = sum(1 for result in results if result["tool_status_pass"])
    coverage_passes = sum(1 for result in results if result["coverage_pass"])
    defect_passes = sum(1 for result in results if result["defect_grounding_pass"])
    blocked_passes = sum(1 for result in results if result["blocked_grounding_pass"])
    evidence_passes = sum(1 for result in results if result["evidence_pass"])
    return {
        "cases": total,
        "case_passes": case_passes,
        "case_pass_rate": _ratio(case_passes, total),
        "report_status_matches": report_status_passes,
        "report_status_rate": _ratio(report_status_passes, total),
        "summary_fact_quality_matches": summary_fact_passes,
        "summary_fact_quality_rate": _ratio(summary_fact_passes, total),
        "tool_status_matches": tool_status_passes,
        "tool_status_rate": _ratio(tool_status_passes, total),
        "coverage_matches": coverage_passes,
        "coverage_match_rate": _ratio(coverage_passes, total),
        "defect_grounding_matches": defect_passes,
        "defect_grounding_rate": _ratio(defect_passes, total),
        "blocked_grounding_matches": blocked_passes,
        "blocked_grounding_rate": _ratio(blocked_passes, total),
        "evidence_matches": evidence_passes,
        "evidence_rate": _ratio(evidence_passes, total),
    }


def print_summary(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    print("Test execution evaluation")
    print(f"Cases: {summary['cases']}")
    print(
        "Case pass rate: "
        f"{summary['case_passes']}/{summary['cases']} = {summary['case_pass_rate']}"
    )
    print(
        "Report status rate: "
        f"{summary['report_status_matches']}/{summary['cases']} = "
        f"{summary['report_status_rate']}"
    )
    print(
        "Summary fact quality rate: "
        f"{summary['summary_fact_quality_matches']}/{summary['cases']} = "
        f"{summary['summary_fact_quality_rate']}"
    )
    print(
        "Tool status rate: "
        f"{summary['tool_status_matches']}/{summary['cases']} = "
        f"{summary['tool_status_rate']}"
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
        "Blocked grounding rate: "
        f"{summary['blocked_grounding_matches']}/{summary['cases']} = "
        f"{summary['blocked_grounding_rate']}"
    )
    print(
        "Evidence rate: "
        f"{summary['evidence_matches']}/{summary['cases']} = {summary['evidence_rate']}"
    )
    for result in results:
        status = "PASS" if result["case_pass"] else "FAIL"
        print(f"- {status} {result['id']}: {result['actual_report_status']}")


def _execution_service_for_case(case: dict[str, Any]) -> ToolExecutionService:
    plan = TestPlan.model_validate(case["plan"])
    adapters = {}
    tools = {step.tool for step in plan.steps}
    if TestToolType.http in tools:
        adapters[TestToolType.http] = HTTPToolAdapter(
            base_url="http://testserver",
            transport=httpx.MockTransport(_http_handler(case.get("http_responses", []))),
        )
    if TestToolType.pytest in tools:
        adapters[TestToolType.pytest] = PytestToolAdapter(
            project_root=project_root,
            allowed_paths=("tests",),
            runner=_pytest_runner(case.get("pytest_results", [])),
        )
    return ToolExecutionService(adapters=adapters)


def _http_handler(responses: Any) -> Callable[[httpx.Request], httpx.Response]:
    response_map = {
        (str(item.get("method", "GET")).upper(), str(item.get("path", "/"))): item
        for item in responses
        if isinstance(item, dict)
    }

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method.upper(), request.url.path)
        response = response_map.get(key)
        if response is None:
            return httpx.Response(404, json={"error": "not configured"})
        status = int(response.get("status", 200))
        if "json" in response:
            return httpx.Response(status, json=response["json"])
        return httpx.Response(status, text=str(response.get("text", "")))

    return handler


def _pytest_runner(results: Any):
    configured = [item for item in results if isinstance(item, dict)]

    def runner(
        command: list[str],
        timeout_seconds: float,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        del timeout_seconds, env
        command_text = " ".join(command)
        for result in configured:
            test_path = str(result.get("test_path", ""))
            if test_path and test_path in command_text:
                return subprocess.CompletedProcess(
                    command,
                    int(result.get("returncode", 1)),
                    stdout=str(result.get("stdout", "")),
                    stderr=str(result.get("stderr", "")),
                )
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=f"No pytest result configured for command: {command_text}",
        )

    return runner


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


def _blocked_steps_match_expected(
    *,
    tool_runs: list[ToolRun],
    expected_step_ids: list[str],
) -> bool:
    return set(_blocked_step_ids(tool_runs)) == set(expected_step_ids)


def _evidence_contains_expected_fragments(
    *,
    report_markdown: str,
    tool_runs: list[ToolRun],
    expected: dict[str, Any],
) -> bool:
    fragments = [str(value) for value in expected.get("output_fragments", [])]
    evidence = "\n".join(
        [
            report_markdown,
            *(
                " ".join(
                    [
                        tool_run.plan_step_id,
                        tool_run.status.value,
                        " ".join(tool_run.command),
                        tool_run.output_summary,
                    ]
                )
                for tool_run in tool_runs
            ),
        ]
    )
    return all(fragment in evidence for fragment in fragments)


def _defect_step_ids(defects: list[str]) -> list[str]:
    return [defect.split(":", 1)[0].strip() for defect in defects if ":" in defect]


def _blocked_step_ids(tool_runs: list[ToolRun]) -> list[str]:
    return [
        tool_run.plan_step_id
        for tool_run in tool_runs
        if tool_run.status.value == "blocked"
    ]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


def _below_thresholds(summary: dict[str, Any], args: argparse.Namespace) -> bool:
    return (
        summary["case_pass_rate"] < args.fail_under_case_pass_rate
        or summary["report_status_rate"] < args.fail_under_report_status_rate
        or summary["summary_fact_quality_rate"]
        < args.fail_under_summary_fact_quality_rate
        or summary["tool_status_rate"] < args.fail_under_tool_status_rate
        or summary["coverage_match_rate"] < args.fail_under_coverage_match_rate
        or summary["defect_grounding_rate"] < args.fail_under_defect_grounding_rate
        or summary["blocked_grounding_rate"] < args.fail_under_blocked_grounding_rate
        or summary["evidence_rate"] < args.fail_under_evidence_rate
    )


if __name__ == "__main__":
    raise SystemExit(main())
