import pytest

from app.core.config import Settings
from app.models.test_case import GenerateRequest, KnowledgeChunk
from app.services.generator import OutputValidationError, TestCaseGenerator as GeneratorService
from app.services.llm import LLMError


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def generate_json(self, messages):
        self.messages.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeRag:
    def __init__(self, chunks=None):
        self.chunks = chunks or []
        self.calls = []

    def search(self, query: str, top_k: int):
        self.calls.append((query, top_k))
        return self.chunks


def _case(title: str, case_id: str = "TC-001", case_type: str = "functional"):
    return {
        "id": case_id,
        "title": title,
        "precondition": "用户已满足前置条件",
        "steps": ["执行操作"],
        "expected": ["返回预期结果"],
        "type": case_type,
    }


def _generator(
    llm: FakeLLM,
    rag: FakeRag | None = None,
    retries: int = 1,
    *,
    review_retry_enabled: bool = False,
    review_min_score: int = 50,
) -> GeneratorService:
    return GeneratorService(
        settings=Settings(
            zhipu_chat_model="fake-model",
            llm_max_retries=retries,
            agent_review_retry_enabled=review_retry_enabled,
            agent_review_min_score=review_min_score,
        ),
        llm=llm,
        rag=rag or FakeRag(),
    )


def test_generate_success_with_context_and_metadata() -> None:
    context = KnowledgeChunk(
        content="JWT 登录需要返回角色和能力",
        source="knowledge_export/api/auth_permissions.md",
        document_type="api",
        module="auth_permissions",
        chunk=1,
    )
    llm = FakeLLM([{"cases": [_case("JWT 登录成功")]}])
    rag = FakeRag([context])

    response = _generator(llm, rag).generate(
        GenerateRequest(
            description="生成 JWT 登录测试用例",
            max_cases=3,
            knowledge_top_k=2,
            include_context=True,
        )
    )

    assert rag.calls == [("生成 JWT 登录测试用例", 2)]
    assert response.cases[0].title == "JWT 登录成功"
    assert response.metadata.model == "fake-model"
    assert response.metadata.attempts == 1
    assert response.metadata.retrieved_chunks == 1
    assert response.metadata.retrieved_sources == ["knowledge_export/api/auth_permissions.md"]
    assert response.metadata.prompt_version == "test-case-generation-v1"
    assert response.metadata.usage.prompt_characters > 0
    assert response.metadata.usage.completion_characters > 0
    assert response.metadata.usage.total_tokens_estimate > 0
    assert response.metadata.review is not None
    assert response.metadata.review.passed is True
    workflow_names = [step.name for step in response.metadata.workflow_steps]
    assert workflow_names[:3] == [
        "analyze_requirement",
        "retrieve_knowledge",
        "plan_test_strategy",
    ]
    assert "call_llm" in workflow_names
    assert "review_cases" in workflow_names
    assert "route_after_review" in workflow_names
    assert "estimate_usage" in workflow_names
    assert response.retrieved_context == [context]


def test_generate_accepts_test_cases_alias() -> None:
    llm = FakeLLM([{"test_cases": [_case("别名字段用例")]}])

    response = _generator(llm).generate(GenerateRequest(description="生成登录测试用例"))

    assert response.cases[0].title == "别名字段用例"


def test_generate_accepts_top_level_list() -> None:
    llm = FakeLLM([[_case("顶层列表用例")]])

    response = _generator(llm).generate(GenerateRequest(description="生成登录测试用例"))

    assert response.cases[0].title == "顶层列表用例"


def test_generate_retries_after_validation_error() -> None:
    llm = FakeLLM(
        [
            {"cases": [{"title": "缺少字段"}]},
            {"cases": [_case("修复后的用例")]},
        ]
    )

    response = _generator(llm, retries=1).generate(
        GenerateRequest(description="生成登录测试用例")
    )

    assert response.metadata.attempts == 2
    assert response.metadata.usage.prompt_characters > 0
    assert response.metadata.usage.completion_characters > 0
    validation_steps = [
        step for step in response.metadata.workflow_steps if step.name == "validate_output"
    ]
    assert [step.status for step in validation_steps] == ["failed", "success"]
    assert response.cases[0].title == "修复后的用例"
    assert "上一次输出需要修正" in llm.messages[1][1]["content"]


def test_generate_retries_when_reviewer_requests_repair() -> None:
    llm = FakeLLM(
        [
            {"cases": [_case("只覆盖登录成功")]},
            {
                "cases": [
                    _case("登录成功", "TC-001", "functional"),
                    _case("手机号为空", "TC-002", "boundary"),
                    _case("验证码错误", "TC-003", "exception"),
                    _case("无权限登录", "TC-004", "permission"),
                    _case("SQL 注入防护", "TC-005", "security"),
                ]
            },
        ]
    )

    response = _generator(
        llm,
        retries=1,
        review_retry_enabled=True,
        review_min_score=70,
    ).generate(
        GenerateRequest(
            description="生成登录测试用例",
            max_cases=5,
            knowledge_top_k=0,
        )
    )

    review_steps = [
        step for step in response.metadata.workflow_steps if step.name == "review_cases"
    ]
    route_steps = [
        step for step in response.metadata.workflow_steps if step.name == "route_after_review"
    ]
    assert response.metadata.attempts == 2
    assert response.metadata.review is not None
    assert response.metadata.review.passed is True
    assert "passed=False" in review_steps[0].summary
    assert "passed=True" in review_steps[1].summary
    assert route_steps[0].summary == "decision=retry, reason=review_feedback"
    assert "Reviewer Agent 审查未通过" in llm.messages[1][1]["content"]


def test_generate_truncates_to_max_cases() -> None:
    llm = FakeLLM(
        [
            {
                "cases": [
                    _case("用例 1", "TC-001"),
                    _case("用例 2", "TC-002"),
                    _case("用例 3", "TC-003"),
                ]
            }
        ]
    )

    response = _generator(llm).generate(
        GenerateRequest(description="生成登录测试用例", max_cases=2)
    )

    assert [case.title for case in response.cases] == ["用例 1", "用例 2"]
    assert [case.id for case in response.cases] == ["TC-001", "TC-002"]


def test_generate_deduplicates_titles_and_reorders_ids() -> None:
    llm = FakeLLM(
        [
            {
                "cases": [
                    _case("重复标题", "CUSTOM-100"),
                    _case("重复标题", "CUSTOM-101"),
                    _case("另一个标题", "CUSTOM-102"),
                ]
            }
        ]
    )

    response = _generator(llm).generate(GenerateRequest(description="生成登录测试用例"))

    assert [case.title for case in response.cases] == ["重复标题", "另一个标题"]
    assert [case.id for case in response.cases] == ["TC-001", "TC-002"]


def test_generate_raises_after_retries_are_exhausted() -> None:
    llm = FakeLLM([{"cases": [{"title": "缺少字段"}]}, {"cases": [{"title": "仍缺少字段"}]}])

    with pytest.raises(OutputValidationError) as error:
        _generator(llm, retries=1).generate(GenerateRequest(description="生成登录测试用例"))

    assert error.value.usage.prompt_characters > 0
    assert error.value.usage.completion_characters > 0


def test_generate_propagates_llm_errors() -> None:
    llm = FakeLLM([LLMError("upstream failed")])

    with pytest.raises(LLMError) as error:
        _generator(llm).generate(GenerateRequest(description="生成登录测试用例"))

    assert error.value.usage.prompt_characters > 0
    assert error.value.usage.completion_characters == 0


def test_generate_handles_empty_rag_results() -> None:
    llm = FakeLLM([{"cases": [_case("无上下文用例")]}])
    rag = FakeRag([])

    response = _generator(llm, rag).generate(
        GenerateRequest(description="生成登录测试用例", knowledge_top_k=0)
    )

    assert response.metadata.retrieved_chunks == 0
    assert response.retrieved_context == []
