from collections import Counter

from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationQualityReport,
    TestCaseType,
)


DEFAULT_TARGET_TYPES = [
    TestCaseType.functional,
    TestCaseType.boundary,
    TestCaseType.exception,
    TestCaseType.permission,
]


def score_generation_quality(
    request: GenerateRequest,
    response: GenerateResponse,
) -> GenerationQualityReport:
    cases = response.cases
    case_count = len(cases)
    duplicate_title_count = _duplicate_title_count([case.title for case in cases])
    duplicate_title_rate = duplicate_title_count / case_count if case_count else 0.0
    covered_types = sorted({case.type for case in cases}, key=lambda item: item.value)
    target_types = request.focus_types or DEFAULT_TARGET_TYPES
    missing_target_types = [item for item in target_types if item not in covered_types]
    type_coverage_rate = (
        (len(target_types) - len(missing_target_types)) / len(target_types)
        if target_types
        else 1.0
    )
    average_steps = _average([len(case.steps) for case in cases])
    average_expected = _average([len(case.expected) for case in cases])
    completeness_rate = _completeness_rate(cases)
    knowledge_grounded = _knowledge_grounded(request, response)

    score = round(
        _case_count_score(case_count)
        + (25 * type_coverage_rate)
        + _step_quality_score(completeness_rate, average_steps)
        + _knowledge_score(request, response)
        + (15 * (1 - duplicate_title_rate))
    )
    warnings, recommendations = _build_feedback(
        request=request,
        case_count=case_count,
        duplicate_title_count=duplicate_title_count,
        missing_target_types=missing_target_types,
        average_steps=average_steps,
        average_expected=average_expected,
        knowledge_grounded=knowledge_grounded,
    )

    return GenerationQualityReport(
        score=max(0, min(100, score)),
        grade=_grade(score),
        case_count=case_count,
        duplicate_title_count=duplicate_title_count,
        duplicate_title_rate=round(duplicate_title_rate, 4),
        covered_types=covered_types,
        missing_target_types=missing_target_types,
        type_coverage_rate=round(type_coverage_rate, 4),
        average_steps=round(average_steps, 2),
        average_expected=round(average_expected, 2),
        knowledge_grounded=knowledge_grounded,
        warnings=warnings,
        recommendations=recommendations,
    )


def _duplicate_title_count(titles: list[str]) -> int:
    normalized = [title.strip().lower() for title in titles if title.strip()]
    counts = Counter(normalized)
    return sum(count - 1 for count in counts.values() if count > 1)


def _average(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _completeness_rate(cases) -> float:
    if not cases:
        return 0.0
    complete = 0
    for case in cases:
        if case.title.strip() and case.steps and case.expected:
            complete += 1
    return complete / len(cases)


def _case_count_score(case_count: int) -> float:
    return min(20.0, case_count * 4.0)


def _step_quality_score(completeness_rate: float, average_steps: float) -> float:
    step_depth_score = min(5.0, max(0.0, average_steps - 1) * 2.5)
    return (15.0 * completeness_rate) + step_depth_score


def _knowledge_grounded(request: GenerateRequest, response: GenerateResponse) -> bool:
    if request.knowledge_top_k <= 0:
        return True
    return response.metadata.retrieved_chunks > 0 and bool(response.metadata.retrieved_sources)


def _knowledge_score(request: GenerateRequest, response: GenerateResponse) -> float:
    if request.knowledge_top_k <= 0:
        return 20.0
    if response.metadata.retrieved_chunks > 0 and response.metadata.retrieved_sources:
        return 20.0
    if response.metadata.retrieved_chunks > 0:
        return 12.0
    return 0.0


def _grade(score: int) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "fair"
    return "poor"


def _build_feedback(
    *,
    request: GenerateRequest,
    case_count: int,
    duplicate_title_count: int,
    missing_target_types: list[TestCaseType],
    average_steps: float,
    average_expected: float,
    knowledge_grounded: bool,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    recommendations: list[str] = []

    if case_count < min(5, request.max_cases):
        warnings.append("case_count_below_recommended")
        recommendations.append("增加用例数量，至少覆盖 5 条核心路径或达到本次 max_cases。")
    if duplicate_title_count:
        warnings.append("duplicate_titles")
        recommendations.append("去除重复标题，避免同一场景被多次生成。")
    if missing_target_types:
        warnings.append("missing_target_types")
        missing = ", ".join(item.value for item in missing_target_types)
        recommendations.append(f"补充缺失的用例类型：{missing}。")
    if average_steps < 2:
        warnings.append("steps_too_shallow")
        recommendations.append("为每条用例补充更完整的操作步骤。")
    if average_expected < 1:
        warnings.append("expected_result_missing")
        recommendations.append("为每条用例补充明确的预期结果。")
    if not knowledge_grounded:
        warnings.append("not_knowledge_grounded")
        recommendations.append("检查知识库召回结果，确保生成内容有业务资料支撑。")

    return warnings, recommendations
