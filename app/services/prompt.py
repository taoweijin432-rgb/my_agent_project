import json

from app.models.test_case import GenerateRequest, KnowledgeChunk


PROMPT_TEMPLATE_VERSION = "test-case-generation-v1"


SYSTEM_PROMPT = """你是资深软件测试架构师。你的任务是把需求描述转换为结构化测试用例。

硬性要求：
1. 只输出一个 JSON object，不要输出 Markdown、解释、注释或多余文本。
2. JSON 顶层字段必须是 cases。
3. cases 中每条用例必须包含 id, title, precondition, steps, expected, type。
4. steps 和 expected 必须是字符串数组。
5. type 只能使用 functional, boundary, exception, permission, compatibility, performance, security。
6. 必须覆盖正常流程、等价类、边界值、异常流和权限校验；如需求明确涉及安全、性能或兼容性，也要覆盖。
7. 不要编造企业知识库没有支持的业务规则；上下文不足时基于输入需求给出可验证假设。
"""


FEW_SHOT_INPUT = "用户登录：手机号和验证码登录，验证码 6 位数字，5 分钟有效。"

FEW_SHOT_OUTPUT = {
    "cases": [
        {
            "id": "TC-001",
            "title": "手机号和有效验证码登录成功",
            "precondition": "用户已注册，验证码在 5 分钟有效期内。",
            "steps": ["输入已注册手机号", "输入正确 6 位验证码", "点击登录"],
            "expected": ["登录成功", "进入系统首页"],
            "type": "functional",
        },
        {
            "id": "TC-002",
            "title": "验证码少于 6 位时登录失败",
            "precondition": "用户已注册。",
            "steps": ["输入已注册手机号", "输入 5 位验证码", "点击登录"],
            "expected": ["登录失败", "提示验证码格式错误"],
            "type": "boundary",
        },
        {
            "id": "TC-003",
            "title": "验证码过期时登录失败",
            "precondition": "验证码生成时间已超过 5 分钟。",
            "steps": ["输入已注册手机号", "输入过期验证码", "点击登录"],
            "expected": ["登录失败", "提示验证码已过期"],
            "type": "exception",
        },
    ]
}


def build_generation_messages(
    request: GenerateRequest,
    contexts: list[KnowledgeChunk],
    correction: str | None = None,
) -> list[dict[str, str]]:
    focus_types = ", ".join(item.value for item in request.focus_types or [])
    context_text = _format_contexts(contexts)
    schema = {
        "cases": [
            {
                "id": "TC-001",
                "title": "string",
                "precondition": "string",
                "steps": ["string"],
                "expected": ["string"],
                "type": "functional|boundary|exception|permission|compatibility|performance|security",
            }
        ]
    }

    user_prompt = f"""请基于以下需求生成测试用例。

需求描述：
{request.description}

企业知识库检索结果：
{context_text}

生成数量上限：{request.max_cases}
优先关注类型：{focus_types or "自动判断"}

Few-shot 输入：
{FEW_SHOT_INPUT}

Few-shot 输出：
{json.dumps(FEW_SHOT_OUTPUT, ensure_ascii=False)}

目标 JSON Schema 示例：
{json.dumps(schema, ensure_ascii=False)}
"""
    if correction:
        user_prompt += f"\n上一次输出没有通过后端校验，请修正后重新输出。校验错误：{correction}\n"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _format_contexts(contexts: list[KnowledgeChunk]) -> str:
    if not contexts:
        return "无相关知识库上下文。"
    blocks = []
    for index, chunk in enumerate(contexts, start=1):
        blocks.append(f"[{index}] source={chunk.source}\n{chunk.content}")
    return "\n\n".join(blocks)
