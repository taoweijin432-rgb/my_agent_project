import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.models.test_case import (
    CoverageEvaluationRequest,
    GenerateRequest,
    RequirementPoint,
    TestCase,
)
from app.services.coverage import evaluate_requirement_coverage
from app.services.generator import TestCaseGenerator
from app.services.llm import LLMClient
from app.services.rag import RagService


def main() -> None:
    args = parse_args()
    requirements = load_requirements(args.requirements)

    if args.generate:
        if not args.description and not args.description_file:
            raise SystemExit("--generate requires --description or --description-file")
        description = args.description or read_text(args.description_file)
        started = time.perf_counter()
        cases = generate_cases(
            description,
            max_cases=args.max_cases,
            knowledge_top_k=args.knowledge_top_k,
        )
        ai_minutes = (time.perf_counter() - started) / 60
        ai_time_source = "measured_generate"
        case_source = "live_generation"
    else:
        if not args.cases:
            raise SystemExit("Provide --cases or use --generate")
        cases = load_cases(args.cases)
        ai_minutes = args.ai_minutes
        ai_time_source = "provided_ai_minutes"
        case_source = args.cases

    coverage = evaluate_requirement_coverage(
        CoverageEvaluationRequest(
            requirements=requirements,
            cases=cases,
            min_keyword_match_ratio=args.min_keyword_match_ratio,
        )
    )
    summary = build_summary(
        manual_minutes=args.manual_minutes,
        ai_minutes=ai_minutes,
        ai_time_source=ai_time_source,
        case_source=case_source,
        coverage=coverage.model_dump(mode="json"),
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        output = resolve_path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(summary), encoding="utf-8")
        print(f"Wrote report: {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare manual test design baseline with generated test cases.",
    )
    parser.add_argument(
        "--requirements",
        required=True,
        help="JSON file containing requirement points.",
    )
    parser.add_argument(
        "--cases",
        help="JSON file containing generated test cases. Omit when using --generate.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Call the project generation chain and measure elapsed time.",
    )
    parser.add_argument("--description", help="Requirement text used with --generate.")
    parser.add_argument(
        "--description-file",
        help="Requirement text file used with --generate.",
    )
    parser.add_argument("--max-cases", type=int, default=12)
    parser.add_argument("--knowledge-top-k", type=int, default=5)
    parser.add_argument("--manual-minutes", type=float, default=35.0)
    parser.add_argument(
        "--ai-minutes",
        type=float,
        default=1.0,
        help="Measured AI generation/review minutes when --cases is used.",
    )
    parser.add_argument("--min-keyword-match-ratio", type=float, default=1.0)
    parser.add_argument("--output", help="Optional Markdown report path.")
    return parser.parse_args()


def load_requirements(path: str) -> list[RequirementPoint]:
    raw = load_json(path)
    items = raw.get("requirements") if isinstance(raw, dict) else raw
    return [RequirementPoint.model_validate(item) for item in items]


def load_cases(path: str) -> list[TestCase]:
    raw = load_json(path)
    items = raw.get("cases") if isinstance(raw, dict) else raw
    return [TestCase.model_validate(item) for item in items]


def load_json(path: str) -> Any:
    return json.loads(resolve_path(path).read_text(encoding="utf-8"))


def read_text(path: str | None) -> str:
    if not path:
        return ""
    return resolve_path(path).read_text(encoding="utf-8")


def resolve_path(path: str) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return PROJECT_ROOT / target


def generate_cases(
    description: str,
    *,
    max_cases: int,
    knowledge_top_k: int,
) -> list[TestCase]:
    settings = get_settings()
    generator = TestCaseGenerator(
        settings=settings,
        llm=LLMClient(settings),
        rag=RagService(settings),
    )
    response = generator.generate(
        GenerateRequest(
            description=description,
            max_cases=max_cases,
            knowledge_top_k=knowledge_top_k,
            include_context=True,
        )
    )
    return response.cases


def build_summary(
    *,
    manual_minutes: float,
    ai_minutes: float,
    ai_time_source: str,
    case_source: str,
    coverage: dict[str, Any],
) -> dict[str, Any]:
    saved_minutes = max(0.0, manual_minutes - ai_minutes)
    reduction_rate = saved_minutes / manual_minutes if manual_minutes > 0 else 0.0
    return {
        "manual_baseline_minutes": round(manual_minutes, 2),
        "ai_generation_minutes": round(ai_minutes, 2),
        "ai_time_source": ai_time_source,
        "case_source": case_source,
        "saved_minutes": round(saved_minutes, 2),
        "time_reduction_rate": round(reduction_rate, 4),
        "coverage": coverage,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    coverage = summary["coverage"]
    lines = [
        "# AI Test Case Generation Efficiency Report",
        "",
        "## Time",
        "",
        f"- Manual baseline: {summary['manual_baseline_minutes']} minutes",
        f"- AI generation and review: {summary['ai_generation_minutes']} minutes",
        f"- AI time source: {summary['ai_time_source']}",
        f"- Case source: {summary['case_source']}",
        f"- Saved time: {summary['saved_minutes']} minutes",
        f"- Time reduction rate: {summary['time_reduction_rate']:.2%}",
        "",
        "## Requirement Coverage",
        "",
        f"- Requirements: {coverage['covered_requirements']}/{coverage['total_requirements']}",
        f"- Coverage rate: {coverage['coverage_rate']:.2%}",
        f"- Keyword coverage rate: {coverage['keyword_coverage_rate']:.2%}",
        "",
        "| Requirement | Covered | Score | Matched Cases | Missing Keywords |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in coverage["items"]:
        requirement = item["requirement"]
        lines.append(
            "| "
            + requirement["id"]
            + " "
            + requirement["title"]
            + " | "
            + ("yes" if item["covered"] else "no")
            + " | "
            + f"{item['coverage_score']:.2%}"
            + " | "
            + ", ".join(item["matched_case_ids"])
            + " | "
            + ", ".join(item["missing_keywords"])
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
