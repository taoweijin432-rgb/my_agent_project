import argparse
import hashlib
import json
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.core.config import get_settings
from app.models.test_case import RequirementPoint
from app.models.test_plan import (
    HTTPToolArgs,
    PytestToolArgs,
    TestPlan,
    TestPlanGenerationRequest,
    TestToolType,
    ToolRun,
)
from app.services.llm import LLMClient
from app.services.prompt import TEST_PLAN_PROMPT_TEMPLATE_VERSION
from app.services.test_plan_generator import LLMTestPlanGenerator, TestPlanGenerator
from app.services.test_report import build_execution_report, export_execution_report
from app.services.tool_adapters import HTTPToolAdapter, PytestToolAdapter
from app.services.tool_execution import ToolAdapter, ToolExecutionService


DEFAULT_CASES_PATH = (
    project_root / "tests" / "fixtures" / "test_agent_workflow_eval_cases.json"
)
DEFAULT_LLM_CACHE_DIR = project_root / "data" / "llm-eval-cache"
LLM_CACHE_VERSION = 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate requirements-to-report test agent workflow quality.",
    )
    parser.add_argument(
        "--cases",
        default=str(DEFAULT_CASES_PATH),
        help="Test agent workflow eval cases JSON.",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    parser.add_argument("--use-llm", action="store_true", help="Evaluate the real LLM planner.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of cases to evaluate concurrently.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run only the selected case id. Repeat to select multiple cases.",
    )
    parser.add_argument(
        "--case-slice",
        default="",
        help="Run a 0-based case slice in START:END form after case-id filtering.",
    )
    parser.add_argument(
        "--case-delay-seconds",
        type=float,
        default=0.0,
        help="Sleep between serial cases to reduce real LLM rate-limit pressure.",
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Allow LLM planner to fall back to the deterministic planner.",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Reuse cached real LLM responses for identical prompts.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Call the real LLM and overwrite cached responses.",
    )
    parser.add_argument(
        "--llm-cache-dir",
        default=str(DEFAULT_LLM_CACHE_DIR),
        help="Directory for cached real LLM responses.",
    )
    parser.add_argument("--fail-under-case-pass-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-tool-args-schema-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-plan-tool-hit-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-plan-test-type-hit-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-plan-step-count-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-risk-keyword-hit-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-report-status-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-summary-fact-quality-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-tool-status-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-coverage-match-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-defect-grounding-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-reason-classification-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-reason-aware-recommendation-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-recommendation-grounding-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-next-action-quality-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-evidence-artifact-quality-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-evidence-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-http-header-value-rate", type=float, default=0.0)
    parser.add_argument("--strict-plan-tools", action="store_true")
    parser.add_argument("--strict-plan-test-types", action="store_true")
    parser.add_argument("--strict-http-headers", action="store_true")
    parser.add_argument("--fail-over-total-ms", type=float, default=0.0)
    parser.add_argument("--fail-over-plan-generation-ms", type=float, default=0.0)
    parser.add_argument("--fail-over-tool-execution-ms", type=float, default=0.0)
    parser.add_argument("--fail-over-report-build-ms", type=float, default=0.0)
    parser.add_argument(
        "--benchmark-history-jsonl",
        default="",
        help="Append benchmark summary to this JSONL file.",
    )
    args = parser.parse_args(argv)
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    if args.case_delay_seconds < 0:
        parser.error("--case-delay-seconds must be greater than or equal to 0")
    if args.case_delay_seconds > 0 and args.concurrency > 1:
        parser.error("--case-delay-seconds requires --concurrency 1")
    if (args.use_cache or args.refresh_cache) and not args.use_llm:
        parser.error("--use-cache and --refresh-cache require --use-llm")

    try:
        cases = select_cases(
            load_cases(Path(args.cases)),
            case_ids=args.case_id,
            case_slice=args.case_slice,
        )
    except ValueError as exc:
        parser.error(str(exc))
    generator = build_generator(
        use_llm=args.use_llm,
        allow_fallback=args.allow_fallback,
        use_cache=args.use_cache,
        refresh_cache=args.refresh_cache,
        cache_dir=Path(args.llm_cache_dir),
    )
    results = evaluate_cases(
        cases,
        generator=generator,
        concurrency=args.concurrency,
        case_delay_seconds=args.case_delay_seconds,
        strict_plan_tools=args.strict_plan_tools,
        strict_plan_test_types=args.strict_plan_test_types,
        strict_http_headers=args.strict_http_headers,
    )
    summary = summarize_results(results)
    if args.benchmark_history_jsonl:
        append_benchmark_history(
            Path(args.benchmark_history_jsonl),
            args=args,
            summary=summary,
        )

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
        raise ValueError("Test agent workflow eval cases must be a JSON array.")
    return cases


def select_cases(
    cases: list[dict[str, Any]],
    *,
    case_ids: list[str] | None = None,
    case_slice: str = "",
) -> list[dict[str, Any]]:
    selected = cases
    requested_ids = [case_id for case_id in case_ids or [] if case_id]
    if requested_ids:
        case_by_id = {str(case.get("id", "")): case for case in cases}
        missing_ids = [case_id for case_id in requested_ids if case_id not in case_by_id]
        if missing_ids:
            raise ValueError(f"Unknown case id(s): {', '.join(missing_ids)}")
        selected = [case_by_id[case_id] for case_id in requested_ids]
    if case_slice:
        start, end = _parse_case_slice(case_slice)
        selected = selected[start:end]
    if not selected:
        raise ValueError("No workflow eval cases selected.")
    return selected


def _parse_case_slice(value: str) -> tuple[int | None, int | None]:
    if ":" not in value:
        raise ValueError("--case-slice must use START:END form")
    raw_start, raw_end = value.split(":", 1)
    start = _parse_slice_bound(raw_start, "--case-slice start")
    end = _parse_slice_bound(raw_end, "--case-slice end")
    if start is not None and end is not None and end < start:
        raise ValueError("--case-slice end must be greater than or equal to start")
    return start, end


def _parse_slice_bound(value: str, label: str) -> int | None:
    if value == "":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{label} must be greater than or equal to 0")
    return parsed


def append_benchmark_history(
    path: Path,
    *,
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> None:
    settings = get_settings()
    record = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend": "llm" if args.use_llm else "deterministic",
        "model": settings.zhipu_chat_model if args.use_llm else None,
        "base_url": settings.zhipu_base_url.rstrip("/") if args.use_llm else None,
        "prompt_template_version": TEST_PLAN_PROMPT_TEMPLATE_VERSION,
        "cases_path": str(Path(args.cases)),
        "case_count": summary.get("cases"),
        "case_ids": list(args.case_id),
        "case_slice": args.case_slice,
        "concurrency": args.concurrency,
        "case_delay_seconds": args.case_delay_seconds,
        "allow_fallback": args.allow_fallback,
        "use_cache": args.use_cache,
        "refresh_cache": args.refresh_cache,
        "thresholds": {
            "fail_over_total_ms": args.fail_over_total_ms,
            "fail_over_plan_generation_ms": args.fail_over_plan_generation_ms,
            "fail_over_tool_execution_ms": args.fail_over_tool_execution_ms,
            "fail_over_report_build_ms": args.fail_over_report_build_ms,
        },
        "summary": summary,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, sort_keys=True)
        file.write("\n")


class CachedLLMClient:
    def __init__(
        self,
        llm: LLMClient,
        *,
        cache_dir: Path,
        refresh: bool = False,
    ):
        self.llm = llm
        self.settings = llm.settings
        self.cache_dir = cache_dir
        self.refresh = refresh
        self._lock = threading.Lock()
        self._local = threading.local()
        self.last_call_metrics = None
        self.last_cache_status = "none"

    @property
    def last_call_metrics(self) -> Any:
        return getattr(self._local, "last_call_metrics", None)

    @last_call_metrics.setter
    def last_call_metrics(self, value: Any) -> None:
        self._local.last_call_metrics = value

    @property
    def last_cache_status(self) -> str:
        return str(getattr(self._local, "last_cache_status", "none"))

    @last_cache_status.setter
    def last_cache_status(self, value: str) -> None:
        self._local.last_cache_status = value

    def generate_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.last_call_metrics = None
        self.last_cache_status = "none"
        cache_path = self._cache_path(messages)
        if not self.refresh:
            cached = self._read_cached_response(cache_path)
            if cached is not None:
                self.last_cache_status = "hit"
                return cached

        self.last_cache_status = "refresh" if self.refresh else "miss"
        response = self.llm.generate_json(messages)
        self.last_call_metrics = getattr(self.llm, "last_call_metrics", None)
        self._write_cached_response(cache_path, messages, response)
        return response

    def _cache_path(self, messages: list[dict[str, str]]) -> Path:
        return self.cache_dir / f"{self._cache_key(messages)}.json"

    def _cache_key(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "cache_version": LLM_CACHE_VERSION,
            "prompt_template_version": TEST_PLAN_PROMPT_TEMPLATE_VERSION,
            "model": self.settings.zhipu_chat_model,
            "base_url": self.settings.zhipu_base_url.rstrip("/"),
            "messages": messages,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _read_cached_response(self, cache_path: Path) -> dict[str, Any] | None:
        with self._lock:
            if not cache_path.exists():
                return None
            with cache_path.open("r", encoding="utf-8") as file:
                cached = json.load(file)
        if not isinstance(cached, dict):
            return None
        if cached.get("cache_version") != LLM_CACHE_VERSION:
            return None
        response = cached.get("response")
        return response if isinstance(response, dict) else None

    def _write_cached_response(
        self,
        cache_path: Path,
        messages: list[dict[str, str]],
        response: dict[str, Any],
    ) -> None:
        record = {
            "cache_version": LLM_CACHE_VERSION,
            "prompt_template_version": TEST_PLAN_PROMPT_TEMPLATE_VERSION,
            "model": self.settings.zhipu_chat_model,
            "base_url": self.settings.zhipu_base_url.rstrip("/"),
            "messages_sha256": self._cache_key(messages),
            "response": response,
        }
        with self._lock:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            temp_path = cache_path.with_suffix(f".{threading.get_ident()}.tmp")
            with temp_path.open("w", encoding="utf-8") as file:
                json.dump(record, file, ensure_ascii=False, indent=2, sort_keys=True)
                file.write("\n")
            temp_path.replace(cache_path)


def build_generator(
    *,
    use_llm: bool,
    allow_fallback: bool,
    use_cache: bool = False,
    refresh_cache: bool = False,
    cache_dir: Path = DEFAULT_LLM_CACHE_DIR,
) -> TestPlanGenerator | LLMTestPlanGenerator:
    if not use_llm:
        return TestPlanGenerator()
    base_llm = LLMClient(get_settings())
    llm: LLMClient | CachedLLMClient = base_llm
    if use_cache or refresh_cache:
        llm = CachedLLMClient(base_llm, cache_dir=cache_dir, refresh=refresh_cache)
    return LLMTestPlanGenerator(
        llm,
        allow_fallback=allow_fallback,
    )


def evaluate_cases(
    cases: list[dict[str, Any]],
    *,
    generator: TestPlanGenerator | LLMTestPlanGenerator,
    concurrency: int = 1,
    case_delay_seconds: float = 0.0,
    strict_plan_tools: bool = False,
    strict_plan_test_types: bool = False,
    strict_http_headers: bool = False,
) -> list[dict[str, Any]]:
    if case_delay_seconds < 0:
        raise ValueError("case_delay_seconds must be greater than or equal to 0.")
    if case_delay_seconds > 0 and concurrency > 1:
        raise ValueError("case_delay_seconds requires concurrency=1.")
    if concurrency <= 1 or len(cases) <= 1:
        results: list[dict[str, Any]] = []
        for index, case in enumerate(cases):
            if index > 0 and case_delay_seconds > 0:
                time.sleep(case_delay_seconds)
            results.append(
                evaluate_case(
                case,
                generator=generator,
                strict_plan_tools=strict_plan_tools,
                strict_plan_test_types=strict_plan_test_types,
                strict_http_headers=strict_http_headers,
            )
            )
        return results
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        return list(
            executor.map(
                lambda case: evaluate_case(
                    case,
                    generator=generator,
                    strict_plan_tools=strict_plan_tools,
                    strict_plan_test_types=strict_plan_test_types,
                    strict_http_headers=strict_http_headers,
                ),
                cases,
            )
        )


def evaluate_case(
    case: dict[str, Any],
    *,
    generator: TestPlanGenerator | LLMTestPlanGenerator,
    strict_plan_tools: bool = False,
    strict_plan_test_types: bool = False,
    strict_http_headers: bool = False,
) -> dict[str, Any]:
    request = _request_from_case(case)
    case_started = time.perf_counter()
    plan_generation_started = time.perf_counter()
    plan = generator.generate(request)
    plan_generation_ms = _elapsed_ms(plan_generation_started)
    llm_observability = _llm_observability(generator)
    tool_arg_errors = _tool_arg_schema_errors(plan)
    tool_args_schema_pass = not tool_arg_errors
    tool_execution_started = time.perf_counter()
    tool_runs = _execution_service_for_case(plan, case).execute_plan(plan)
    tool_execution_ms = _elapsed_ms(tool_execution_started)
    report_build_started = time.perf_counter()
    report = build_execution_report(plan, tool_runs)
    report_build_ms = _elapsed_ms(report_build_started)
    markdown = export_execution_report(report, "markdown")
    total_ms = _elapsed_ms(case_started)
    expected = case.get("expected") or {}

    actual_tools = sorted({step.tool.value for step in plan.steps})
    actual_test_types = sorted(
        {
            test_type.value
            for step in plan.steps
            for test_type in step.test_types
        }
    )
    expected_tools = [str(value) for value in expected.get("plan_tools", [])]
    expected_test_types = [str(value) for value in expected.get("plan_test_types", [])]
    expected_step_count = expected.get("generated_step_count")
    risk_keywords = [str(value) for value in expected.get("risk_keywords", [])]
    risk_text = "\n".join(plan.scope.risks)
    matched_risk_keywords = [keyword for keyword in risk_keywords if keyword in risk_text]

    actual_tool_statuses = {
        tool_run.plan_step_id: tool_run.status.value for tool_run in tool_runs
    }
    expected_tool_statuses = {
        str(step_id): str(status)
        for step_id, status in (expected.get("tool_run_statuses") or {}).items()
    }
    http_header_value_errors = (
        _http_header_value_errors(plan) if strict_http_headers else []
    )

    plan_tool_pass = (
        _matches_exactly(actual_tools, expected_tools)
        if strict_plan_tools
        else _contains_all(actual_tools, expected_tools)
    )
    plan_test_type_pass = (
        _matches_exactly(actual_test_types, expected_test_types)
        if strict_plan_test_types
        else _contains_all(actual_test_types, expected_test_types)
    )
    http_header_value_pass = not http_header_value_errors
    plan_step_count_pass = (
        expected_step_count is None or len(plan.steps) == int(expected_step_count)
    )
    risk_keyword_pass = _contains_all(matched_risk_keywords, risk_keywords)
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
    recommendation_pass = _recommendations_ground_expected_steps(
        recommendations=report.recommendations,
        tool_runs=tool_runs,
        expected_step_ids=[
            str(value)
            for value in expected.get(
                "recommendation_step_ids",
                _default_recommendation_step_ids(tool_runs),
            )
        ],
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
    evidence_pass = _evidence_contains_expected_fragments(
        report_markdown=markdown,
        tool_runs=tool_runs,
        expected=expected,
    )
    failure_reasons = _failure_reasons(
        checks=[
            (
                "tool_args_schema_mismatch",
                tool_args_schema_pass,
                "valid executable tool args",
                tool_arg_errors,
            ),
            (
                "http_header_value_mismatch",
                http_header_value_pass,
                "valid HTTP header values",
                http_header_value_errors,
            ),
            (
                "plan_tool_mismatch",
                plan_tool_pass,
                expected_tools,
                actual_tools,
            ),
            (
                "plan_test_type_mismatch",
                plan_test_type_pass,
                expected_test_types,
                actual_test_types,
            ),
            (
                "plan_step_count_mismatch",
                plan_step_count_pass,
                expected_step_count,
                len(plan.steps),
            ),
            (
                "risk_keyword_mismatch",
                risk_keyword_pass,
                risk_keywords,
                matched_risk_keywords,
            ),
            (
                "report_status_mismatch",
                report_status_pass,
                expected.get("report_status", ""),
                report.status.value,
            ),
            (
                "summary_fact_quality_mismatch",
                summary_fact_pass,
                "status, execution counts, coverage, and terminal status counts",
                report.summary,
            ),
            (
                "tool_status_mismatch",
                tool_status_pass,
                expected_tool_statuses,
                actual_tool_statuses,
            ),
            (
                "coverage_mismatch",
                coverage_pass,
                {
                    "covered": expected.get("covered_requirement_ids", []),
                    "uncovered": expected.get("uncovered_requirement_ids", []),
                },
                report.requirement_coverage,
            ),
            (
                "defect_grounding_mismatch",
                defect_pass,
                expected.get("defect_step_ids", []),
                _defect_step_ids(report.defects),
            ),
            (
                "reason_classification_mismatch",
                reason_classification_pass,
                expected_reason_classifications,
                report.reason_classifications,
            ),
            (
                "recommendation_grounding_mismatch",
                recommendation_pass,
                expected.get(
                    "recommendation_step_ids",
                    _default_recommendation_step_ids(tool_runs),
                ),
                report.recommendations,
            ),
            (
                "reason_aware_recommendation_mismatch",
                reason_aware_recommendation_pass,
                reason_aware_keywords_by_step_id,
                report.recommendations,
            ),
            (
                "next_action_quality_mismatch",
                next_action_pass,
                next_action_keywords_by_step_id,
                report.recommendations,
            ),
            (
                "evidence_artifact_quality_mismatch",
                evidence_artifact_pass,
                evidence_step_ids,
                "report markdown tool run evidence",
            ),
            (
                "evidence_mismatch",
                evidence_pass,
                expected.get("output_fragments", []),
                "report markdown and tool output summaries",
            ),
        ]
    )

    return {
        "id": str(case.get("id", "")),
        "description": str(case.get("description", "")),
        "case_pass": (
            tool_args_schema_pass
            and http_header_value_pass
            and plan_tool_pass
            and plan_test_type_pass
            and plan_step_count_pass
            and risk_keyword_pass
            and report_status_pass
            and summary_fact_pass
            and tool_status_pass
            and coverage_pass
            and defect_pass
            and reason_classification_pass
            and reason_aware_recommendation_pass
            and recommendation_pass
            and next_action_pass
            and evidence_artifact_pass
            and evidence_pass
        ),
        "tool_args_schema_pass": tool_args_schema_pass,
        "tool_arg_errors": tool_arg_errors,
        "http_header_value_pass": http_header_value_pass,
        "http_header_value_errors": http_header_value_errors,
        "strict_plan_tools": strict_plan_tools,
        "strict_plan_test_types": strict_plan_test_types,
        "strict_http_headers": strict_http_headers,
        "plan_tool_pass": plan_tool_pass,
        "plan_test_type_pass": plan_test_type_pass,
        "plan_step_count_pass": plan_step_count_pass,
        "risk_keyword_pass": risk_keyword_pass,
        "report_status_pass": report_status_pass,
        "summary_fact_quality_pass": summary_fact_pass,
        "tool_status_pass": tool_status_pass,
        "coverage_pass": coverage_pass,
        "defect_grounding_pass": defect_pass,
        "reason_classification_pass": reason_classification_pass,
        "reason_aware_recommendation_pass": reason_aware_recommendation_pass,
        "recommendation_grounding_pass": recommendation_pass,
        "next_action_quality_pass": next_action_pass,
        "evidence_artifact_quality_pass": evidence_artifact_pass,
        "evidence_pass": evidence_pass,
        "failure_codes": [reason["code"] for reason in failure_reasons],
        "failure_reasons": failure_reasons,
        "expected_plan_tools": expected_tools,
        "actual_plan_tools": actual_tools,
        "expected_plan_test_types": expected_test_types,
        "actual_plan_test_types": actual_test_types,
        "expected_generated_step_count": expected_step_count,
        "actual_generated_step_count": len(plan.steps),
        "expected_risk_keywords": risk_keywords,
        "matched_risk_keywords": matched_risk_keywords,
        "expected_report_status": str(expected.get("report_status", "")),
        "actual_report_status": report.status.value,
        "expected_tool_run_statuses": expected_tool_statuses,
        "actual_tool_run_statuses": actual_tool_statuses,
        "actual_requirement_coverage": report.requirement_coverage,
        "expected_defect_step_ids": [
            str(value) for value in expected.get("defect_step_ids", [])
        ],
        "actual_defect_step_ids": _defect_step_ids(report.defects),
        "expected_reason_classifications": expected_reason_classifications,
        "actual_reason_classifications": report.reason_classifications,
        "expected_reason_aware_keywords_by_step_id": reason_aware_keywords_by_step_id,
        "expected_recommendation_step_ids": [
            str(value)
            for value in expected.get(
                "recommendation_step_ids",
                _default_recommendation_step_ids(tool_runs),
            )
        ],
        "expected_next_action_keywords_by_step_id": next_action_keywords_by_step_id,
        "expected_evidence_step_ids": evidence_step_ids,
        "timing_ms": {
            "total": total_ms,
            "plan_generation": plan_generation_ms,
            "tool_execution": tool_execution_ms,
            "report_build": report_build_ms,
        },
        "llm_observability": llm_observability,
        "plan": _plan_summary(plan),
        "report": {
            "id": report.id,
            "summary": report.summary,
            "defects": report.defects,
            "reason_classifications": report.reason_classifications,
            "recommendations": report.recommendations,
        },
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    case_passes = sum(1 for result in results if result["case_pass"])
    tool_args_schema_passes = sum(
        1 for result in results if result["tool_args_schema_pass"]
    )
    http_header_value_passes = sum(
        1 for result in results if result["http_header_value_pass"]
    )
    plan_tool_passes = sum(1 for result in results if result["plan_tool_pass"])
    expected_type_total = sum(len(result["expected_plan_test_types"]) for result in results)
    matched_type_total = sum(
        len(set(result["expected_plan_test_types"]).intersection(result["actual_plan_test_types"]))
        for result in results
    )
    plan_step_count_passes = sum(
        1 for result in results if result["plan_step_count_pass"]
    )
    expected_risk_total = sum(len(result["expected_risk_keywords"]) for result in results)
    matched_risk_total = sum(len(result["matched_risk_keywords"]) for result in results)
    report_status_passes = sum(1 for result in results if result["report_status_pass"])
    summary_fact_passes = sum(
        1 for result in results if result["summary_fact_quality_pass"]
    )
    tool_status_passes = sum(1 for result in results if result["tool_status_pass"])
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
    evidence_passes = sum(1 for result in results if result["evidence_pass"])
    failure_code_counts = Counter(
        code
        for result in results
        for code in result.get("failure_codes", [])
    )
    timing_summary = _summarize_eval_timings(results)
    llm_observability = _summarize_llm_observability(results)
    return {
        "cases": total,
        "case_passes": case_passes,
        "case_pass_rate": _ratio(case_passes, total),
        "tool_args_schema_matches": tool_args_schema_passes,
        "tool_args_schema_rate": _ratio(tool_args_schema_passes, total),
        "http_header_value_matches": http_header_value_passes,
        "http_header_value_rate": _ratio(http_header_value_passes, total),
        "plan_tool_matches": plan_tool_passes,
        "plan_tool_hit_rate": _ratio(plan_tool_passes, total),
        "plan_test_type_hits": matched_type_total,
        "plan_test_type_total": expected_type_total,
        "plan_test_type_hit_rate": _ratio(matched_type_total, expected_type_total),
        "plan_step_count_matches": plan_step_count_passes,
        "plan_step_count_rate": _ratio(plan_step_count_passes, total),
        "risk_keyword_hits": matched_risk_total,
        "risk_keyword_total": expected_risk_total,
        "risk_keyword_hit_rate": _ratio(matched_risk_total, expected_risk_total),
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
        "evidence_matches": evidence_passes,
        "evidence_rate": _ratio(evidence_passes, total),
        "failure_code_counts": dict(sorted(failure_code_counts.items())),
        "strict_modes": {
            "plan_tools": any(result["strict_plan_tools"] for result in results),
            "plan_test_types": any(
                result["strict_plan_test_types"] for result in results
            ),
            "http_headers": any(result["strict_http_headers"] for result in results),
        },
        "timing_ms": timing_summary,
        "llm_observability": llm_observability,
    }


def print_summary(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    print("Test agent workflow evaluation")
    print(f"Cases: {summary['cases']}")
    print(
        "Case pass rate: "
        f"{summary['case_passes']}/{summary['cases']} = {summary['case_pass_rate']}"
    )
    print(
        "Plan tool hit rate: "
        f"{summary['plan_tool_matches']}/{summary['cases']} = "
        f"{summary['plan_tool_hit_rate']}"
    )
    print(
        "Tool args schema rate: "
        f"{summary['tool_args_schema_matches']}/{summary['cases']} = "
        f"{summary['tool_args_schema_rate']}"
    )
    print(
        "HTTP header value rate: "
        f"{summary['http_header_value_matches']}/{summary['cases']} = "
        f"{summary['http_header_value_rate']}"
    )
    print(
        "Plan step count rate: "
        f"{summary['plan_step_count_matches']}/{summary['cases']} = "
        f"{summary['plan_step_count_rate']}"
    )
    print(
        "Plan test type hit rate: "
        f"{summary['plan_test_type_hits']}/{summary['plan_test_type_total']} = "
        f"{summary['plan_test_type_hit_rate']}"
    )
    print(
        "Risk keyword hit rate: "
        f"{summary['risk_keyword_hits']}/{summary['risk_keyword_total']} = "
        f"{summary['risk_keyword_hit_rate']}"
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
        "Evidence rate: "
        f"{summary['evidence_matches']}/{summary['cases']} = {summary['evidence_rate']}"
    )
    print(f"Timing ms: {summary['timing_ms']}")
    print(f"LLM observability: {summary['llm_observability']}")
    for result in results:
        status = "PASS" if result["case_pass"] else "FAIL"
        print(
            f"- {status} {result['id']}: {result['actual_report_status']} "
            f"timing_ms={result.get('timing_ms', {})}"
        )
        for reason in result.get("failure_reasons", []):
            print(f"  - {reason['code']}: {reason['message']}")


def _request_from_case(case: dict[str, Any]) -> TestPlanGenerationRequest:
    return TestPlanGenerationRequest(
        description=str(case["description"]),
        source=case.get("source"),
        max_steps=int(case.get("max_steps", 5)),
        requirements=[
            RequirementPoint.model_validate(requirement)
            for requirement in case.get("requirements", [])
        ],
    )


def _execution_service_for_case(
    plan: TestPlan,
    case: dict[str, Any],
) -> ToolExecutionService:
    adapters: dict[TestToolType, ToolAdapter] = {}
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


def _tool_arg_schema_errors(plan: TestPlan) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for step in plan.steps:
        if step.tool == TestToolType.http:
            schema: type[BaseModel] = HTTPToolArgs
        elif step.tool == TestToolType.pytest:
            schema = PytestToolArgs
        else:
            continue
        try:
            schema.model_validate(step.tool_args)
        except Exception as exc:
            errors.append(
                {
                    "step_id": step.id,
                    "tool": step.tool.value,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return errors


def _http_handler(responses: Any) -> Callable[[httpx.Request], httpx.Response]:
    response_map = {
        (str(item.get("method", "GET")).upper(), str(item.get("path", "/"))): item
        for item in responses
        if isinstance(item, dict)
    }

    def handler(request: httpx.Request) -> httpx.Response:
        response = response_map.get((request.method.upper(), request.url.path))
        if response is None:
            return httpx.Response(404, json={"error": "not configured"})
        status = int(response.get("status", 200))
        if "json" in response:
            return httpx.Response(status, json=response["json"])
        return httpx.Response(status, text=str(response.get("text", "")))

    return handler


def _pytest_runner(
    results: Any,
) -> Callable[[list[str], float, dict[str, str]], subprocess.CompletedProcess[str]]:
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
            _contains_evidence_fragment(markdown, fragment)
            for fragment in evidence_fragments
        ):
            return False
    return True


def _contains_evidence_fragment(markdown: str, fragment: str) -> bool:
    if fragment in markdown:
        return True
    normalized_markdown = " ".join(markdown.split())
    normalized_fragment = " ".join(fragment.split())
    return bool(normalized_fragment and normalized_fragment in normalized_markdown)


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
                "tool_args": step.tool_args,
            }
            for step in plan.steps
        ],
        "risks": plan.scope.risks,
    }


def _defect_step_ids(defects: list[str]) -> list[str]:
    return [defect.split(":", 1)[0].strip() for defect in defects if ":" in defect]


def _failure_reasons(
    *,
    checks: list[tuple[str, bool, Any, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "code": code,
            "message": f"expected={expected!r}; actual={actual!r}",
        }
        for code, passed, expected, actual in checks
        if not passed
    ]


def _contains_all(actual: list[str], expected: list[str]) -> bool:
    return set(expected).issubset(actual)


def _matches_exactly(actual: list[str], expected: list[str]) -> bool:
    return set(actual) == set(expected)


def _http_header_value_errors(plan: TestPlan) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for step in plan.steps:
        if step.tool != TestToolType.http:
            continue
        try:
            args = HTTPToolArgs.model_validate(step.tool_args)
        except Exception:
            continue
        for name, value in args.headers.items():
            error = _http_header_value_error(name, value)
            if error:
                errors.append(
                    {
                        "step_id": step.id,
                        "header": name,
                        "value": value,
                        "error": error,
                    }
                )
    return errors


def _http_header_value_error(name: str, value: str) -> str | None:
    header = name.strip().lower()
    text = value.strip()
    if not text:
        return "header value must not be empty"
    if header not in {"accept", "content-type"}:
        return None
    media_type = text.split(";", 1)[0].strip()
    if (
        "/" not in media_type
        or media_type.startswith("/")
        or media_type.endswith("/")
    ):
        return "media type must include a non-empty type and subtype"
    return None


def _summarize_eval_timings(
    results: list[dict[str, Any]],
) -> dict[str, dict[str, float | int | None]]:
    samples: dict[str, list[float]] = {
        "total": [],
        "plan_generation": [],
        "tool_execution": [],
        "report_build": [],
    }
    for result in results:
        timing = result.get("timing_ms")
        if not isinstance(timing, dict):
            continue
        for name in samples:
            value = timing.get(name)
            if isinstance(value, int | float):
                samples[name].append(float(value))
    return {name: _timing_stats(values) for name, values in samples.items()}


def _llm_observability(
    generator: TestPlanGenerator | LLMTestPlanGenerator,
) -> dict[str, Any]:
    if not isinstance(generator, LLMTestPlanGenerator):
        return {}

    details: dict[str, Any] = {
        "used_llm": True,
        "used_fallback": generator.last_used_fallback,
    }
    cache_status = getattr(generator.llm, "last_cache_status", None)
    if isinstance(cache_status, str) and cache_status != "none":
        details["cache_status"] = cache_status
    metrics = getattr(generator.llm, "last_call_metrics", None)
    if metrics is not None:
        details["llm"] = metrics.to_safe_dict()
    return details


def _summarize_llm_observability(results: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [
        details
        for result in results
        if isinstance(details := result.get("llm_observability"), dict)
        and details.get("used_llm") is True
    ]
    llm_metrics = [
        metrics
        for details in observed
        if isinstance(metrics := details.get("llm"), dict)
    ]
    attempts = [
        attempt
        for metrics in llm_metrics
        for attempt in metrics.get("attempts", [])
        if isinstance(attempt, dict)
    ]
    error_code_counts = Counter(
        str(error_code)
        for attempt in attempts
        if isinstance(error_code := attempt.get("error_code"), str)
    )
    cache_status_counts = Counter(
        str(cache_status)
        for details in observed
        if isinstance(cache_status := details.get("cache_status"), str)
    )
    total_durations = [
        float(duration)
        for metrics in llm_metrics
        if isinstance(duration := metrics.get("total_duration_ms"), int | float)
    ]
    attempt_durations = [
        float(duration)
        for attempt in attempts
        if isinstance(duration := attempt.get("duration_ms"), int | float)
    ]
    attempt_count_total = sum(
        int(count)
        for metrics in llm_metrics
        if isinstance(count := metrics.get("attempt_count"), int)
    )
    retry_count_total = sum(
        int(count)
        for metrics in llm_metrics
        if isinstance(count := metrics.get("retry_count"), int)
    )
    return {
        "observed_cases": len(observed),
        "fallback_used_cases": sum(1 for details in observed if details.get("used_fallback")),
        "cache_status_counts": dict(sorted(cache_status_counts.items())),
        "attempt_count_total": attempt_count_total,
        "retry_count_total": retry_count_total,
        "timeout_count": error_code_counts.get("timeout", 0),
        "error_code_counts": dict(sorted(error_code_counts.items())),
        "total_duration_ms": _timing_stats(total_durations),
        "attempt_duration_ms": _timing_stats(attempt_durations),
    }


def _timing_stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "avg": None, "max": None}
    return {
        "count": len(values),
        "avg": round(sum(values) / len(values), 3),
        "max": round(max(values), 3),
    }


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 3)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


def _below_thresholds(summary: dict[str, Any], args: argparse.Namespace) -> bool:
    return (
        summary["case_pass_rate"] < args.fail_under_case_pass_rate
        or summary["tool_args_schema_rate"] < args.fail_under_tool_args_schema_rate
        or summary["plan_tool_hit_rate"] < args.fail_under_plan_tool_hit_rate
        or summary["plan_test_type_hit_rate"] < args.fail_under_plan_test_type_hit_rate
        or summary["plan_step_count_rate"] < args.fail_under_plan_step_count_rate
        or summary["risk_keyword_hit_rate"] < args.fail_under_risk_keyword_hit_rate
        or summary["report_status_rate"] < args.fail_under_report_status_rate
        or summary["summary_fact_quality_rate"]
        < args.fail_under_summary_fact_quality_rate
        or summary["tool_status_rate"] < args.fail_under_tool_status_rate
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
        or summary["evidence_rate"] < args.fail_under_evidence_rate
        or (
            summary["http_header_value_rate"]
            < args.fail_under_http_header_value_rate
        )
        or _timing_exceeds(summary, "total", args.fail_over_total_ms)
        or _timing_exceeds(
            summary,
            "plan_generation",
            args.fail_over_plan_generation_ms,
        )
        or _timing_exceeds(
            summary,
            "tool_execution",
            args.fail_over_tool_execution_ms,
        )
        or _timing_exceeds(
            summary,
            "report_build",
            args.fail_over_report_build_ms,
        )
    )


def _timing_exceeds(
    summary: dict[str, Any],
    name: str,
    limit_ms: float,
) -> bool:
    if limit_ms <= 0:
        return False
    timing = summary.get("timing_ms")
    if not isinstance(timing, dict):
        return False
    stats = timing.get(name)
    if not isinstance(stats, dict):
        return False
    max_value = stats.get("max")
    return isinstance(max_value, int | float) and float(max_value) > limit_ms


if __name__ == "__main__":
    raise SystemExit(main())
