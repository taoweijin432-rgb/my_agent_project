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
8. 如果用户指定了优先关注类型，且生成数量允许，每个指定类型至少生成 1 条用例。
9. 企业知识库中的数字、时长、次数、状态、权限、安全约束必须转成可验证的 steps 或 expected。
10. 每条用例的 expected 必须包含可检查的断言，不要只写“符合预期”。
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
    strategy: str | None = None,
) -> list[dict[str, str]]:
    focus_types = ", ".join(item.value for item in request.focus_types or [])
    context_text = _format_contexts(contexts)
    coverage_instruction = _coverage_instruction(request)
    context_instruction = _context_instruction(contexts)
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

测试策略规划：
{strategy or "自动规划"}

生成数量上限：{request.max_cases}
优先关注类型：{focus_types or "自动判断"}

覆盖矩阵要求：
{coverage_instruction}

知识库使用要求：
{context_instruction}

Few-shot 输入：
{FEW_SHOT_INPUT}

Few-shot 输出：
{json.dumps(FEW_SHOT_OUTPUT, ensure_ascii=False)}

注意：Few-shot 只用于演示 JSON 格式和用例粒度，不代表本次业务规则。
如果 Few-shot 与本次需求或知识库冲突，必须以本次需求和知识库为准，不要复制 Few-shot 的登录方式、字段或规则。

目标 JSON Schema 示例：
{json.dumps(schema, ensure_ascii=False)}
"""
    if correction:
        user_prompt += (
            "\n上一次输出需要修正，请根据以下反馈重新输出。"
            "如果已达到生成数量上限，必须替换低价值或重复场景，"
            "不要保留仍缺失目标类型或验收点的结果。"
            f"反馈：{correction}\n"
        )

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


def _coverage_instruction(request: GenerateRequest) -> str:
    focus_types = [item.value for item in request.focus_types or []]
    if not focus_types:
        return (
            "- 至少覆盖 functional、boundary、exception、permission；"
            "如果需求涉及安全、性能或兼容性，也必须补充对应类型。"
        )
    if len(focus_types) <= request.max_cases:
        return (
            "- 必须覆盖以下全部类型，且每个类型至少 1 条："
            f"{', '.join(focus_types)}。\n"
            f"- 前 {len(focus_types)} 条用例的 type 必须依次覆盖："
            f"{', '.join(focus_types)}；不要把边界值、权限或安全场景都归为 exception。\n"
            "- 剩余名额优先补充风险最高、最容易漏测的边界、权限和安全场景。"
        )
    return (
        "- 生成数量少于关注类型数量，必须优先覆盖风险最高的类型："
        f"{', '.join(focus_types)}。\n"
        "- 未覆盖的关注类型必须在用例标题或预期中体现为后续补测建议。"
    )


def _context_instruction(contexts: list[KnowledgeChunk]) -> str:
    if not contexts:
        return (
            "- 当前没有召回知识库上下文；只能基于用户需求生成，并在 precondition "
            "或 expected 中写明可验证假设。"
        )
    return (
        "- 优先从企业知识库检索结果提取验收点并转成测试断言。\n"
        "- 对知识库中的状态、阈值、有效期、次数限制、权限规则、安全规则逐项覆盖。\n"
        "- 对长度、范围、最小值、最大值等规则必须生成 boundary 类型用例。\n"
        "- 对账号枚举、token 泄露、注入、暴力破解等安全规则必须生成 security 类型用例或明确断言。\n"
        "- 对“不累计”“不能暴露”“不能写入日志”等否定规则，expected 必须写明禁止发生的结果。\n"
        "- 用例标题或预期应体现关键规则，例如锁定次数、锁定时长、token 有效期、"
        "验证码有效期、角色权限、审计字段或安全防护。"
    )
