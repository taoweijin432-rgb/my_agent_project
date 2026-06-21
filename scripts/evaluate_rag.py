import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.core.config import get_settings
from app.models.test_case import KnowledgeChunk
from app.services.rag import RagService


DEFAULT_CASES_PATH = project_root / "tests" / "fixtures" / "rag_eval_cases.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval quality.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH), help="RAG eval cases JSON.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--case-keyword-ratio", type=float, default=0.5)
    parser.add_argument("--fail-under-source-hit-rate", type=float, default=0.0)
    parser.add_argument("--fail-under-keyword-hit-rate", type=float, default=0.0)
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    service = RagService(get_settings())
    results = evaluate_cases(
        cases,
        search_fn=lambda query, top_k: service.search(query, top_k=top_k),
        top_k=args.top_k,
        case_keyword_ratio=args.case_keyword_ratio,
    )
    summary = summarize_results(results)

    if args.json:
        print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
    else:
        print_summary(summary, results)

    if (
        summary["source_hit_rate"] < args.fail_under_source_hit_rate
        or summary["keyword_hit_rate"] < args.fail_under_keyword_hit_rate
    ):
        raise SystemExit(1)


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list):
        raise ValueError("RAG eval cases must be a JSON array.")
    return cases


def evaluate_cases(
    cases: list[dict[str, Any]],
    *,
    search_fn: Callable[[str, int], list[KnowledgeChunk]],
    top_k: int,
    case_keyword_ratio: float = 0.5,
) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        chunks = search_fn(str(case["query"]), top_k)
        results.append(evaluate_case(case, chunks, case_keyword_ratio=case_keyword_ratio))
    return results


def evaluate_case(
    case: dict[str, Any],
    chunks: list[KnowledgeChunk],
    *,
    case_keyword_ratio: float = 0.5,
) -> dict[str, Any]:
    expected_sources = {_normalize_source(source) for source in case.get("expected_sources", [])}
    actual_sources = [_normalize_source(chunk.source) for chunk in chunks]
    matched_sources = sorted(set(actual_sources).intersection(expected_sources))
    source_pass = bool(matched_sources)

    expected_keywords = [str(keyword) for keyword in case.get("expected_keywords", [])]
    combined_text = "\n".join(
        [chunk.content for chunk in chunks]
        + [chunk.source for chunk in chunks]
        + [chunk.document_type or "" for chunk in chunks]
        + [chunk.module or "" for chunk in chunks]
    )
    matched_keywords = [
        keyword for keyword in expected_keywords if keyword.lower() in combined_text.lower()
    ]
    keyword_ratio = len(matched_keywords) / len(expected_keywords) if expected_keywords else 1.0
    keyword_pass = keyword_ratio >= case_keyword_ratio

    return {
        "id": case.get("id", ""),
        "query": case.get("query", ""),
        "source_pass": source_pass,
        "keyword_pass": keyword_pass,
        "case_pass": source_pass and keyword_pass,
        "expected_sources": sorted(expected_sources),
        "actual_sources": actual_sources,
        "matched_sources": matched_sources,
        "expected_keywords": expected_keywords,
        "matched_keywords": matched_keywords,
        "keyword_ratio": round(keyword_ratio, 4),
        "top_results": [
            {
                "source": _normalize_source(chunk.source),
                "score": chunk.score,
                "document_type": chunk.document_type,
                "module": chunk.module,
                "chunk": chunk.chunk,
            }
            for chunk in chunks
        ],
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    source_hits = sum(1 for result in results if result["source_pass"])
    keyword_hits = sum(len(result["matched_keywords"]) for result in results)
    keyword_total = sum(len(result["expected_keywords"]) for result in results)
    case_passes = sum(1 for result in results if result["case_pass"])
    return {
        "cases": total,
        "source_hits": source_hits,
        "source_hit_rate": round(source_hits / total, 4) if total else 0.0,
        "keyword_hits": keyword_hits,
        "keyword_total": keyword_total,
        "keyword_hit_rate": round(keyword_hits / keyword_total, 4) if keyword_total else 0.0,
        "case_passes": case_passes,
        "case_pass_rate": round(case_passes / total, 4) if total else 0.0,
    }


def print_summary(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    print("RAG evaluation")
    print(f"Cases: {summary['cases']}")
    print(f"Source hit rate: {summary['source_hits']}/{summary['cases']} = {summary['source_hit_rate']}")
    print(
        "Keyword hit rate: "
        f"{summary['keyword_hits']}/{summary['keyword_total']} = {summary['keyword_hit_rate']}"
    )
    print(f"Case pass rate: {summary['case_passes']}/{summary['cases']} = {summary['case_pass_rate']}")
    print("")
    for result in results:
        status = "PASS" if result["case_pass"] else "FAIL"
        print(f"[{status}] {result['id']}")
        print(f"  query: {result['query']}")
        print(f"  matched_sources: {', '.join(result['matched_sources']) or '-'}")
        print(f"  matched_keywords: {', '.join(result['matched_keywords']) or '-'}")
        print(f"  top_sources: {', '.join(result['actual_sources']) or '-'}")


def _normalize_source(source: str) -> str:
    return str(source).replace("\\", "/").strip()


if __name__ == "__main__":
    main()
