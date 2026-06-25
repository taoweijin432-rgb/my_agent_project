from app.models.test_case import (
    GenerateRequest,
    KnowledgeChunk,
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
    assert CaseType.boundary in review.missing_target_types
    assert "Reviewer Agent 审查未通过" in feedback
    assert "必须补齐缺失用例类型" in feedback
    assert "必须替换低价值、重复或泛化用例" in feedback


def test_reviewer_recommends_retry_for_missing_acceptance_keywords() -> None:
    review = review_generated_cases(
        request=GenerateRequest(
            description="登录需要覆盖 SQL 注入、暴力破解、管理员和普通用户权限。",
            knowledge_top_k=0,
            focus_types=[CaseType.functional, CaseType.security],
        ),
        cases=[
            _case("登录成功", CaseType.functional),
            _case("通用安全防护", CaseType.security),
        ],
        model="fake-model",
        attempt=1,
        retrieved_chunks=0,
        retrieved_sources=[],
        min_score=70,
    )

    assert review.passed is False
    assert review.retry_recommended is True
    assert "missing_acceptance_keywords" in review.warnings
    assert "SQL 注入" in review.missing_acceptance_keywords
    assert "暴力破解" in review.missing_acceptance_keywords


def test_reviewer_checks_acceptance_keywords_from_retrieved_context() -> None:
    review = review_generated_cases(
        request=GenerateRequest(
            description="生成登录测试用例",
            knowledge_top_k=2,
            focus_types=[CaseType.functional, CaseType.security],
        ),
        cases=[
            _case("登录成功", CaseType.functional),
            _case("通用安全防护", CaseType.security),
        ],
        model="fake-model",
        attempt=1,
        retrieved_chunks=1,
        retrieved_sources=["knowledge/prd/login.md"],
        retrieved_contexts=[
            KnowledgeChunk(
                source="knowledge/prd/login.md",
                content="登录安全验收必须覆盖 SQL 注入、暴力破解和账号枚举。",
            )
        ],
        min_score=70,
    )

    assert review.passed is False
    assert review.retry_recommended is True
    assert "missing_acceptance_keywords" in review.warnings
    assert "账号枚举" in review.missing_acceptance_keywords
