from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationMetadata,
    GenerationReview,
    KnowledgeChunk,
    TestCase,
)
from app.services.prompt import PROMPT_TEMPLATE_VERSION
from app.services.quality import score_generation_quality


BLOCKING_WARNINGS = {
    "duplicate_titles",
    "expected_result_missing",
    "missing_target_types",
    "missing_acceptance_keywords",
}


def review_generated_cases(
    *,
    request: GenerateRequest,
    cases: list[TestCase],
    model: str,
    attempt: int,
    retrieved_chunks: int,
    retrieved_sources: list[str],
    min_score: int,
    retrieved_contexts: list[KnowledgeChunk] | None = None,
) -> GenerationReview:
    response = GenerateResponse(
        cases=cases,
        metadata=GenerationMetadata(
            model=model,
            attempts=attempt,
            retrieved_chunks=retrieved_chunks,
            retrieved_sources=retrieved_sources,
            prompt_version=PROMPT_TEMPLATE_VERSION,
        ),
        retrieved_context=retrieved_contexts or [],
    )
    quality = score_generation_quality(request, response)
    blocking = [warning for warning in quality.warnings if warning in BLOCKING_WARNINGS]
    passed = quality.score >= min_score and not blocking

    return GenerationReview(
        passed=passed,
        score=quality.score,
        grade=quality.grade,
        warnings=quality.warnings,
        recommendations=quality.recommendations,
        missing_target_types=quality.missing_target_types,
        missing_acceptance_keywords=quality.missing_acceptance_keywords,
        retry_recommended=not passed,
    )


def build_review_feedback(review: GenerationReview) -> str:
    warnings = ", ".join(review.warnings) or "none"
    recommendations = "；".join(review.recommendations) or "无"
    repair_instructions: list[str] = []
    if review.missing_target_types:
        missing_types = ", ".join(item.value for item in review.missing_target_types)
        repair_instructions.append(
            "必须补齐缺失用例类型，并让 type 字段准确使用："
            f"{missing_types}。"
        )
    if review.missing_acceptance_keywords:
        missing_keywords = "、".join(review.missing_acceptance_keywords)
        repair_instructions.append(
            "必须补齐缺失关键验收点，每个验收点都要在用例 title、steps "
            f"或 expected 中形成可检查断言：{missing_keywords}。"
        )
    if repair_instructions:
        repair_instructions.append(
            "如果生成数量已达到上限，必须替换低价值、重复或泛化用例，"
            "不要通过超出 max_cases 的方式追加。"
        )
        repair_instructions.append(
            "保留已经覆盖的高价值场景，但最终 JSON 必须整体重新输出完整 cases。"
        )
    repair_text = "；".join(repair_instructions) or "无额外覆盖修复指令。"

    return (
        "Reviewer Agent 审查未通过："
        f"score={review.score}, grade={review.grade}, warnings={warnings}。"
        f"请按以下建议重新生成：{recommendations}。"
        f"覆盖修复要求：{repair_text}"
    )
