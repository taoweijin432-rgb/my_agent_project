from app.models.test_case import GenerateRequest, KnowledgeChunk, TestCaseType as CaseType
from app.services.prompt import build_generation_messages


def test_prompt_requires_each_focus_type_when_capacity_allows() -> None:
    messages = build_generation_messages(
        GenerateRequest(
            description="生成登录测试用例",
            max_cases=5,
            knowledge_top_k=2,
            focus_types=[
                CaseType.functional,
                CaseType.exception,
                CaseType.boundary,
                CaseType.permission,
                CaseType.security,
            ],
        ),
        contexts=[
            KnowledgeChunk(
                content="连续 5 次密码错误后账号锁定 15 分钟。",
                source="knowledge/prd/login.md",
            )
        ],
    )

    user_prompt = messages[1]["content"]

    assert "每个类型至少 1 条" in user_prompt
    assert "前 5 条用例的 type 必须依次覆盖" in user_prompt
    assert "不要把边界值、权限或安全场景都归为 exception" in user_prompt
    assert "functional, exception, boundary, permission, security" in user_prompt
    assert "知识库中的状态、阈值、有效期、次数限制、权限规则、安全规则逐项覆盖" in user_prompt
    assert "长度、范围、最小值、最大值" in user_prompt
    assert "账号枚举、token 泄露、注入、暴力破解" in user_prompt
    assert "不累计" in user_prompt
    assert "锁定次数" in user_prompt
    assert "Few-shot 只用于演示 JSON 格式和用例粒度" in user_prompt
    assert "不要复制 Few-shot 的登录方式" in user_prompt


def test_prompt_correction_requires_replacing_low_value_cases() -> None:
    messages = build_generation_messages(
        GenerateRequest(description="生成登录测试用例", max_cases=2),
        contexts=[],
        correction="补充缺失的用例类型：boundary。",
    )

    user_prompt = messages[1]["content"]

    assert "必须替换低价值或重复场景" in user_prompt
    assert "不要保留仍缺失目标类型或验收点的结果" in user_prompt
    assert "补充缺失的用例类型：boundary" in user_prompt


def test_prompt_marks_assumptions_when_knowledge_context_is_empty() -> None:
    messages = build_generation_messages(
        GenerateRequest(description="生成登录测试用例", knowledge_top_k=2),
        contexts=[],
    )

    assert "当前没有召回知识库上下文" in messages[1]["content"]
    assert "写明可验证假设" in messages[1]["content"]
