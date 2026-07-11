import re

from app.models.test_case import (
    CoverageGapKnowledgeRequest,
    CoverageEvaluationRequest,
    CoverageEvaluationResponse,
    KnowledgeDocument,
    RequirementCoverageItem,
    RequirementPoint,
    TestCase,
)


def evaluate_requirement_coverage(
    request: CoverageEvaluationRequest,
) -> CoverageEvaluationResponse:
    items = [
        _evaluate_requirement(
            requirement,
            request.cases,
            min_keyword_match_ratio=request.min_keyword_match_ratio,
        )
        for requirement in request.requirements
    ]
    covered_requirements = sum(1 for item in items if item.covered)
    total_keywords = sum(
        len(_effective_keywords(item.requirement))
        for item in items
    )
    matched_keywords = sum(len(item.matched_keywords) for item in items)
    uncovered_ids = [
        item.requirement.id
        for item in items
        if not item.covered
    ]

    coverage_rate = _ratio(covered_requirements, len(items))
    keyword_coverage_rate = _ratio(matched_keywords, total_keywords)
    warnings, recommendations = _feedback(uncovered_ids, coverage_rate)

    return CoverageEvaluationResponse(
        total_requirements=len(items),
        covered_requirements=covered_requirements,
        coverage_rate=round(coverage_rate, 4),
        total_keywords=total_keywords,
        matched_keywords=matched_keywords,
        keyword_coverage_rate=round(keyword_coverage_rate, 4),
        uncovered_requirement_ids=uncovered_ids,
        items=items,
        warnings=warnings,
        recommendations=recommendations,
    )


def build_coverage_gap_knowledge_document(
    request: CoverageGapKnowledgeRequest,
) -> tuple[KnowledgeDocument, int]:
    gap_items = [
        item
        for item in request.coverage.items
        if request.include_covered or not item.covered
    ]
    if not gap_items:
        raise ValueError("coverage result has no gaps to persist.")

    tags = _dedupe(
        [
            *request.tags,
            request.module,
            "coverage-gap",
            "human-confirmed",
        ]
    )
    document = KnowledgeDocument(
        source=request.source,
        content=_format_gap_document(request, gap_items),
        document_type=request.document_type,
        module=request.module,
        tags=tags,
    )
    return document, len(gap_items)


def _evaluate_requirement(
    requirement: RequirementPoint,
    cases: list[TestCase],
    *,
    min_keyword_match_ratio: float,
) -> RequirementCoverageItem:
    keywords = _effective_keywords(requirement)
    normalized_case_texts = [
        (case, _normalize(_case_text(case)))
        for case in cases
    ]
    matched_keywords: list[str] = []
    for keyword in keywords:
        normalized_keyword = _normalize(keyword)
        if not normalized_keyword:
            continue
        if any(_contains_keyword(text, normalized_keyword) for _, text in normalized_case_texts):
            matched_keywords.append(keyword)

    matched_case_ids: list[str] = []
    matched_case_titles: list[str] = []
    min_case_keywords = _min_case_keywords(len(keywords))
    for case, text in normalized_case_texts:
        case_matched_keywords = [
            keyword
            for keyword in keywords
            if _contains_keyword(text, _normalize(keyword))
        ]
        if len(case_matched_keywords) >= min_case_keywords:
            matched_case_ids.append(case.id)
            matched_case_titles.append(case.title)

    missing_keywords = [
        keyword
        for keyword in keywords
        if keyword not in matched_keywords
    ]
    coverage_score = _ratio(len(matched_keywords), len(keywords))
    return RequirementCoverageItem(
        requirement=requirement,
        covered=coverage_score >= min_keyword_match_ratio,
        coverage_score=round(coverage_score, 4),
        matched_case_ids=matched_case_ids,
        matched_case_titles=matched_case_titles,
        matched_keywords=matched_keywords,
        missing_keywords=missing_keywords,
    )


def _effective_keywords(requirement: RequirementPoint) -> list[str]:
    keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
    if keywords:
        return _dedupe(keywords)
    return [requirement.title]


def _case_text(case: TestCase) -> str:
    return " ".join(
        [
            case.id,
            case.title,
            case.precondition,
            *case.steps,
            *case.expected,
            case.type.value,
        ]
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value.lower())


def _contains_keyword(normalized_text: str, normalized_keyword: str) -> bool:
    if not normalized_keyword:
        return False
    searchable = normalized_text
    for prefix in ("未", "不"):
        searchable = searchable.replace(f"{prefix}{normalized_keyword}", "")
    return normalized_keyword in searchable


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return numerator / denominator


def _min_case_keywords(keyword_count: int) -> int:
    if keyword_count <= 1:
        return 1
    return 2


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _format_gap_document(
    request: CoverageGapKnowledgeRequest,
    items: list[RequirementCoverageItem],
) -> str:
    coverage = request.coverage
    lines = [
        "# 覆盖缺口沉淀",
        "",
        "来源：需求覆盖率评估人工确认。",
        f"需求覆盖：{coverage.covered_requirements}/{coverage.total_requirements}"
        f"（{coverage.coverage_rate:.2%}）。",
        f"关键词覆盖：{coverage.matched_keywords}/{coverage.total_keywords}"
        f"（{coverage.keyword_coverage_rate:.2%}）。",
        "",
        "## 确认缺口",
    ]

    for item in items:
        requirement = item.requirement
        lines.extend(
            [
                "",
                f"### {requirement.id} {requirement.title}",
                f"- 覆盖状态：{'已覆盖' if item.covered else '未覆盖'}",
                f"- 优先级：{requirement.priority}",
                f"- 来源：{requirement.source or '-'}",
                f"- 描述：{requirement.description or '-'}",
                f"- 需求关键词：{_join_or_dash(requirement.keywords)}",
                f"- 已匹配关键词：{_join_or_dash(item.matched_keywords)}",
                f"- 缺失关键词：{_join_or_dash(item.missing_keywords)}",
                f"- 匹配用例：{_join_or_dash(item.matched_case_ids)}",
                "- 建议补充：围绕缺失关键词补充测试用例，并在后续生成时优先检索该缺口。",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def _join_or_dash(values: list[str]) -> str:
    cleaned = [value.strip() for value in values if value.strip()]
    return "、".join(cleaned) if cleaned else "-"


def _feedback(
    uncovered_ids: list[str],
    coverage_rate: float,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    recommendations: list[str] = []
    if uncovered_ids:
        warnings.append("uncovered_requirements")
        recommendations.append(
            "补充未覆盖验收点对应的测试用例："
            + "、".join(uncovered_ids)
            + "。"
        )
    if coverage_rate < 1:
        warnings.append("coverage_below_full")
        recommendations.append("复查 PRD 验收点与测试用例映射，优先补齐高优先级遗漏项。")
    return warnings, recommendations
