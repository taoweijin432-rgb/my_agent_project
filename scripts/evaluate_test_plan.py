import argparse
import json
import sys
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.core.config import get_settings
from app.models.test_case import RequirementPoint
from app.models.test_plan import TestPlan, TestPlanGenerationRequest
from app.services.llm import LLMClient
from app.services.test_plan_generator import LLMTestPlanGenerator, TestPlanGenerator


DEFAULT_CASES_PATH = project_root / "tests" / "fixtures" / "test_plan_eval_cases.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate test plan generation quality.")
    parser.add_argument(
        "--cases",
        default=str(DEFAULT_CASES_PATH),
        help="Test plan eval cases JSON.",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    parser.add_argument("--use-llm", action="store_true", help="Evaluate the real LLM planner.")
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Allow LLM planner to fall back to the deterministic planner.",
    )
    parser.add_argument("--fail-under-case-pass-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-tool-hit-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-test-type-hit-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-risk-keyword-hit-rate", type=float, default=0.0)
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.cases))
    generator = build_generator(use_llm=args.use_llm, allow_fallback=args.allow_fallback)
    results = evaluate_cases(cases, generator=generator)
    summary = summarize_results(results)

    if args.json:
        print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
    else:
        print_summary(summary, results)

    if _below_thresholds(summary, args):
        return 1
    return 0


def build_generator(
    *,
    use_llm: bool,
    allow_fallback: bool,
) -> TestPlanGenerator | LLMTestPlanGenerator:
    if not use_llm:
        return TestPlanGenerator()
    return LLMTestPlanGenerator(
        LLMClient(get_settings()),
        allow_fallback=allow_fallback,
    )


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list):
        raise ValueError("Test plan eval cases must be a JSON array.")
    return cases


def evaluate_cases(
    cases: list[dict[str, Any]],
    *,
    generator: TestPlanGenerator | LLMTestPlanGenerator,
) -> list[dict[str, Any]]:
    return [evaluate_case(case, generator=generator) for case in cases]


def evaluate_case(
    case: dict[str, Any],
    *,
    generator: TestPlanGenerator | LLMTestPlanGenerator,
) -> dict[str, Any]:
    request = _request_from_case(case)
    plan = generator.generate(request)
    expected = case.get("expected") or {}
    expected_tools = [str(value) for value in expected.get("tools", [])]
    expected_test_types = [str(value) for value in expected.get("test_types", [])]
    expected_risk_keywords = [str(value) for value in expected.get("risk_keywords", [])]

    actual_tools = sorted({step.tool.value for step in plan.steps})
    actual_test_types = sorted(
        {
            test_type.value
            for step in plan.steps
            for test_type in step.test_types
        }
    )
    risk_text = "\n".join(plan.scope.risks)
    matched_risk_keywords = [
        keyword for keyword in expected_risk_keywords if keyword in risk_text
    ]

    tool_pass = _contains_all(actual_tools, expected_tools)
    test_type_pass = _contains_all(actual_test_types, expected_test_types)
    risk_keyword_pass = _contains_all(matched_risk_keywords, expected_risk_keywords)
    return {
        "id": str(case.get("id", "")),
        "description": str(case.get("description", "")),
        "case_pass": tool_pass and test_type_pass and risk_keyword_pass,
        "tool_pass": tool_pass,
        "test_type_pass": test_type_pass,
        "risk_keyword_pass": risk_keyword_pass,
        "expected_tools": expected_tools,
        "actual_tools": actual_tools,
        "expected_test_types": expected_test_types,
        "actual_test_types": actual_test_types,
        "expected_risk_keywords": expected_risk_keywords,
        "matched_risk_keywords": matched_risk_keywords,
        "plan": _plan_summary(plan),
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    expected_tool_total = sum(len(result["expected_tools"]) for result in results)
    expected_type_total = sum(len(result["expected_test_types"]) for result in results)
    expected_risk_total = sum(len(result["expected_risk_keywords"]) for result in results)
    matched_tool_total = sum(
        len(set(result["expected_tools"]).intersection(result["actual_tools"]))
        for result in results
    )
    matched_type_total = sum(
        len(set(result["expected_test_types"]).intersection(result["actual_test_types"]))
        for result in results
    )
    matched_risk_total = sum(len(result["matched_risk_keywords"]) for result in results)
    case_passes = sum(1 for result in results if result["case_pass"])
    return {
        "cases": total,
        "case_passes": case_passes,
        "case_pass_rate": _ratio(case_passes, total),
        "tool_hits": matched_tool_total,
        "tool_total": expected_tool_total,
        "tool_hit_rate": _ratio(matched_tool_total, expected_tool_total),
        "test_type_hits": matched_type_total,
        "test_type_total": expected_type_total,
        "test_type_hit_rate": _ratio(matched_type_total, expected_type_total),
        "risk_keyword_hits": matched_risk_total,
        "risk_keyword_total": expected_risk_total,
        "risk_keyword_hit_rate": _ratio(matched_risk_total, expected_risk_total),
    }


def print_summary(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    print("Test plan evaluation")
    print(f"Cases: {summary['cases']}")
    print(
        "Case pass rate: "
        f"{summary['case_passes']}/{summary['cases']} = {summary['case_pass_rate']}"
    )
    print(
        "Tool hit rate: "
        f"{summary['tool_hits']}/{summary['tool_total']} = {summary['tool_hit_rate']}"
    )
    print(
        "Test type hit rate: "
        f"{summary['test_type_hits']}/{summary['test_type_total']} = "
        f"{summary['test_type_hit_rate']}"
    )
    print(
        "Risk keyword hit rate: "
        f"{summary['risk_keyword_hits']}/{summary['risk_keyword_total']} = "
        f"{summary['risk_keyword_hit_rate']}"
    )
    for result in results:
        status = "PASS" if result["case_pass"] else "FAIL"
        print(f"- {status} {result['id']}: {result['plan']['title']}")


def _request_from_case(case: dict[str, Any]) -> TestPlanGenerationRequest:
    return TestPlanGenerationRequest(
        description=str(case["description"]),
        requirements=[
            RequirementPoint.model_validate(requirement)
            for requirement in case.get("requirements", [])
        ],
    )


def _plan_summary(plan: TestPlan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "title": plan.title,
        "steps": [
            {
                "id": step.id,
                "title": step.title,
                "tool": step.tool.value,
                "test_types": [test_type.value for test_type in step.test_types],
                "requirement_ids": step.requirement_ids,
            }
            for step in plan.steps
        ],
        "risks": plan.scope.risks,
    }


def _contains_all(actual: list[str], expected: list[str]) -> bool:
    return set(expected).issubset(actual)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


def _below_thresholds(summary: dict[str, Any], args: argparse.Namespace) -> bool:
    return (
        summary["case_pass_rate"] < args.fail_under_case_pass_rate
        or summary["tool_hit_rate"] < args.fail_under_tool_hit_rate
        or summary["test_type_hit_rate"] < args.fail_under_test_type_hit_rate
        or summary["risk_keyword_hit_rate"] < args.fail_under_risk_keyword_hit_rate
    )


if __name__ == "__main__":
    raise SystemExit(main())
