from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationMetadata,
    GenerationReview,
    TestCase,
)
from app.services.prompt import PROMPT_TEMPLATE_VERSION
from app.services.quality import score_generation_quality


BLOCKING_WARNINGS = {"duplicate_titles", "expected_result_missing"}


def review_generated_cases(
    *,
    request: GenerateRequest,
    cases: list[TestCase],
    model: str,
    attempt: int,
    retrieved_chunks: int,
    retrieved_sources: list[str],
    min_score: int,
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
        retry_recommended=not passed,
    )


def build_review_feedback(review: GenerationReview) -> str:
    warnings = ", ".join(review.warnings) or "none"
    recommendations = "；".join(review.recommendations) or "无"
    return (
        "Reviewer Agent 审查未通过："
        f"score={review.score}, grade={review.grade}, warnings={warnings}。"
        f"请按以下建议重新生成：{recommendations}"
    )
