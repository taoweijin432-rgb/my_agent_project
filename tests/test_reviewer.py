from app.models.test_case import (
    GenerateRequest,
    TestCase as CaseModel,
    TestCaseType as CaseType,
)
from app.services.reviewer import build_review_feedback, review_generated_cases


def _case(title: str, case_type: CaseType, *, steps: int = 2) -> CaseModel:
    return CaseModel(
        id="TC-001",
        title=title,
        precondition="用户满足前置条件",
        steps=[f"步骤 {index}" for index in range(1, steps + 1)],
        expected=["返回预期结果"],
        type=case_type,
    )


def test_reviewer_passes_high_quality_cases() -> None:
    review = review_generated_cases(
        request=GenerateRequest(description="生成登录测试用例", knowledge_top_k=0),
        cases=[
            _case("登录成功", CaseType.functional),
            _case("手机号为空", CaseType.boundary),
            _case("验证码错误", CaseType.exception),
            _case("无权限登录", CaseType.permission),
            _case("SQL 注入防护", CaseType.security),
        ],
        model="fake-model",
        attempt=1,
        retrieved_chunks=0,
        retrieved_sources=[],
        min_score=70,
    )

    assert review.passed is True
    assert review.retry_recommended is False
    assert review.score >= 70


def test_reviewer_recommends_retry_for_low_quality_cases() -> None:
    review = review_generated_cases(
        request=GenerateRequest(
            description="生成登录测试用例",
            max_cases=5,
            knowledge_top_k=0,
        ),
        cases=[_case("只覆盖登录成功", CaseType.functional, steps=1)],
        model="fake-model",
        attempt=1,
        retrieved_chunks=0,
        retrieved_sources=[],
        min_score=70,
    )

    feedback = build_review_feedback(review)

    assert review.passed is False
    assert review.retry_recommended is True
    assert "missing_target_types" in review.warnings
    assert "Reviewer Agent 审查未通过" in feedback
