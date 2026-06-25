from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationMetadata,
    KnowledgeChunk,
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


def test_quality_flags_missing_acceptance_keywords() -> None:
    request = GenerateRequest(
        description=(
            "登录需要覆盖 disabled 用户、deleted 用户、access_token 2 小时、"
            "refresh_token 7 天、管理员和普通用户权限、SQL 注入、暴力破解。"
        ),
        knowledge_top_k=0,
        focus_types=[CaseType.functional, CaseType.security],
    )
    response = GenerateResponse(
        cases=[
            _case("登录成功", CaseType.functional),
            _case("通用安全防护", CaseType.security),
        ],
        metadata=GenerationMetadata(model="fake-model", attempts=1, retrieved_chunks=0),
    )

    quality = score_generation_quality(request, response)

    assert "missing_acceptance_keywords" in quality.warnings
    assert "disabled 用户" in quality.missing_acceptance_keywords
    assert any("disabled 用户" in item for item in quality.recommendations)
    assert quality.score < 100


def test_quality_checks_acceptance_keywords_from_retrieved_context() -> None:
    request = GenerateRequest(
        description="生成登录测试用例",
        knowledge_top_k=2,
        focus_types=[CaseType.functional, CaseType.security],
    )
    response = GenerateResponse(
        cases=[
            _case("登录成功", CaseType.functional),
            _case("通用安全防护", CaseType.security),
        ],
        metadata=GenerationMetadata(
            model="fake-model",
            attempts=1,
            retrieved_chunks=1,
            retrieved_sources=["knowledge/prd/login.md"],
        ),
        retrieved_context=[
            KnowledgeChunk(
                source="knowledge/prd/login.md",
                content=(
                    "登录必须覆盖 deleted 用户、SQL 注入、暴力破解、账号枚举、"
                    "token 泄露、验证码错误不累计密码错误次数。"
                ),
            )
        ],
    )

    quality = score_generation_quality(request, response)

    assert "missing_acceptance_keywords" in quality.warnings
    assert "deleted 用户" in quality.missing_acceptance_keywords
    assert "验证码不累计密码错误次数" in quality.missing_acceptance_keywords


def test_quality_accepts_token_leakage_prevention_phrasing() -> None:
    request = GenerateRequest(
        description="登录必须覆盖 token 泄露。",
        knowledge_top_k=0,
        focus_types=[CaseType.security],
    )
    response = GenerateResponse(
        cases=[
            CaseModel(
                id="TC-001",
                title="token 不出现在 URL、日志、错误提示或审计明文中",
                precondition="用户已登录",
                steps=["检查 URL、日志、错误提示和审计日志"],
                expected=["token 不出现在 URL、日志、错误提示或审计明文中"],
                type=CaseType.security,
            )
        ],
        metadata=GenerationMetadata(model="fake-model", attempts=1, retrieved_chunks=0),
    )

    quality = score_generation_quality(request, response)

    assert "token 泄露" not in quality.missing_acceptance_keywords


def test_quality_requires_audit_log_field_assertions() -> None:
    request = GenerateRequest(
        description="登录成功、失败和锁定都必须写审计日志。",
        knowledge_top_k=0,
        focus_types=[CaseType.functional],
    )
    response = GenerateResponse(
        cases=[
            _case("审计日志记录", CaseType.functional),
        ],
        metadata=GenerationMetadata(model="fake-model", attempts=1, retrieved_chunks=0),
    )

    quality = score_generation_quality(request, response)

    assert "审计日志" in quality.missing_acceptance_keywords


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
