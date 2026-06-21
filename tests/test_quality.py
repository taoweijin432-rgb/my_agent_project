from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationMetadata,
    TestCase as CaseModel,
    TestCaseType as CaseType,
)
from app.services.quality import score_generation_quality


def _case(title: str, case_type: CaseType, *, steps=2) -> CaseModel:
    return CaseModel(
        id="TC-001",
        title=title,
        precondition="用户满足前置条件",
        steps=[f"步骤 {index}" for index in range(1, steps + 1)],
        expected=["返回预期结果"],
        type=case_type,
    )


def test_quality_score_rewards_coverage_and_grounding() -> None:
    request = GenerateRequest(description="生成登录测试用例", knowledge_top_k=3)
    response = GenerateResponse(
        cases=[
            _case("登录成功", CaseType.functional),
            _case("验证码边界值", CaseType.boundary),
            _case("验证码错误", CaseType.exception),
            _case("无权限登录", CaseType.permission),
            _case("SQL 注入防护", CaseType.security),
        ],
        metadata=GenerationMetadata(
            model="fake-model",
            attempts=1,
            retrieved_chunks=2,
            retrieved_sources=["knowledge/prd/login.md"],
        ),
    )

    quality = score_generation_quality(request, response)

    assert quality.score >= 90
    assert quality.grade == "excellent"
    assert quality.duplicate_title_count == 0
    assert quality.type_coverage_rate == 1
    assert quality.knowledge_grounded is True
    assert quality.warnings == []


def test_quality_score_flags_duplicates_missing_types_and_no_grounding() -> None:
    request = GenerateRequest(
        description="生成登录测试用例",
        knowledge_top_k=3,
        focus_types=[CaseType.functional, CaseType.boundary, CaseType.permission],
    )
    response = GenerateResponse(
        cases=[
            _case("登录成功", CaseType.functional, steps=1),
            _case("登录成功", CaseType.functional, steps=1),
        ],
        metadata=GenerationMetadata(
            model="fake-model",
            attempts=1,
            retrieved_chunks=0,
            retrieved_sources=[],
        ),
    )

    quality = score_generation_quality(request, response)

    assert quality.score < 70
    assert quality.grade in {"fair", "poor"}
    assert quality.duplicate_title_count == 1
    assert quality.missing_target_types == [CaseType.boundary, CaseType.permission]
    assert quality.knowledge_grounded is False
    assert "duplicate_titles" in quality.warnings
    assert "missing_target_types" in quality.warnings
    assert "not_knowledge_grounded" in quality.warnings


def test_quality_does_not_penalize_grounding_when_rag_disabled() -> None:
    request = GenerateRequest(description="生成登录测试用例", knowledge_top_k=0)
    response = GenerateResponse(
        cases=[_case("登录成功", CaseType.functional)],
        metadata=GenerationMetadata(
            model="fake-model",
            attempts=1,
            retrieved_chunks=0,
            retrieved_sources=[],
        ),
    )

    quality = score_generation_quality(request, response)

    assert quality.knowledge_grounded is True
    assert "not_knowledge_grounded" not in quality.warnings
