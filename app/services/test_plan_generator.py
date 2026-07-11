import hashlib
import re

from pydantic import ValidationError

from app.models.test_case import KnowledgeChunk, RequirementPoint, TestCaseType
from app.models.test_plan import (
    TestPlan,
    TestPlanGenerationRequest,
    TestPlanPriority,
    TestPlanScope,
    TestPlanStep,
    TestToolType,
)
from app.services.llm import LLMClient, LLMError
from app.services.prompt import build_test_plan_messages


class TestPlanOutputValidationError(RuntimeError):
    pass


class TestPlanGenerator:
    def generate(self, request: TestPlanGenerationRequest) -> TestPlan:
        requirements = request.requirements or [_requirement_from_description(request)]
        steps = [
            _step_for_requirement(requirement, index=index)
            for index, requirement in enumerate(requirements[: request.max_steps], start=1)
        ]
        return TestPlan(
            id=_stable_id("plan", request.source or request.description),
            title=_plan_title(request),
            source=request.source,
            requirements=requirements,
            scope=_scope_for_request(request, requirements),
            steps=steps,
        )


def generate_test_plan(request: TestPlanGenerationRequest) -> TestPlan:
    return TestPlanGenerator().generate(request)


class LLMTestPlanGenerator:
    def __init__(
        self,
        llm: LLMClient,
        *,
        fallback: TestPlanGenerator | None = None,
        allow_fallback: bool = True,
    ):
        self.llm = llm
        self.fallback = fallback or TestPlanGenerator()
        self.allow_fallback = allow_fallback

    def generate(self, request: TestPlanGenerationRequest) -> TestPlan:
        try:
            payload = self.llm.generate_json(build_test_plan_messages(request))
            return _plan_from_llm_payload(payload, request)
        except (LLMError, TestPlanOutputValidationError):
            if self.allow_fallback:
                return self.fallback.generate(request)
            raise


def _requirement_from_description(
    request: TestPlanGenerationRequest,
) -> RequirementPoint:
    return RequirementPoint(
        id="REQ-001",
        title=_short_title(request.description),
        description=request.description,
        keywords=_keywords_from_text(request.description),
        priority="medium",
        source=request.source,
    )


def _step_for_requirement(requirement: RequirementPoint, *, index: int) -> TestPlanStep:
    text = _combined_requirement_text(requirement)
    test_types = _test_types_for_text(text)
    tool = _tool_for_text(text)
    return TestPlanStep(
        id=f"TP-{index:03d}",
        title=f"验证{requirement.title}",
        objective=requirement.description or requirement.title,
        requirement_ids=[requirement.id],
        test_types=test_types,
        priority=TestPlanPriority(requirement.priority),
        tool=tool,
        tool_args=_tool_args_for_requirement(requirement, tool),
        success_criteria=_success_criteria(requirement, test_types),
    )


def _scope_for_request(
    request: TestPlanGenerationRequest,
    requirements: list[RequirementPoint],
) -> TestPlanScope:
    context_sources = _unique_sources(request.context)
    return TestPlanScope(
        in_scope=[requirement.title for requirement in requirements],
        out_of_scope=["非需求描述范围内的功能不纳入本轮计划"],
        assumptions=[
            "测试环境、账号和基础数据已准备完成",
            *([f"参考知识来源：{', '.join(context_sources)}"] if context_sources else []),
        ],
        risks=_risks_for_requirements(requirements, request.context),
    )


def _plan_title(request: TestPlanGenerationRequest) -> str:
    source = request.source.rsplit("/", 1)[-1] if request.source else ""
    if source:
        return f"{source} 测试计划"
    return f"{_short_title(request.description)} 测试计划"


def _test_types_for_text(text: str) -> list[TestCaseType]:
    result = [TestCaseType.functional]
    if _contains_any(text, ("边界", "上限", "下限", "为空", "最大", "最小", "limit")):
        result.append(TestCaseType.boundary)
    if _contains_any(text, ("异常", "失败", "错误", "超时", "冲突", "拒绝", "拦截")):
        result.append(TestCaseType.exception)
    if _contains_any(text, ("权限", "角色", "鉴权", "认证", "token", "auth", "permission")):
        result.append(TestCaseType.permission)
    if _contains_any(text, ("越权", "注入", "敏感", "签名", "密钥", "secret", "security")):
        result.append(TestCaseType.security)
    return _dedupe_test_types(result)


def _tool_for_text(text: str) -> TestToolType:
    if _contains_any(text, ("页面", "浏览器", "按钮", "表单", "ui", "web")):
        return TestToolType.playwright
    if _contains_any(text, ("sql", "mysql", "数据库", "表", "字段")):
        return TestToolType.sql
    if _contains_any(text, ("api", "接口", "http", "post ", "get ", "put ", "delete ")):
        return TestToolType.http
    return TestToolType.manual


def _tool_args_for_requirement(
    requirement: RequirementPoint,
    tool: TestToolType,
) -> dict[str, str]:
    if tool == TestToolType.http:
        return {"target": "api", "requirement_id": requirement.id}
    if tool == TestToolType.playwright:
        return {"target": "ui", "requirement_id": requirement.id}
    if tool == TestToolType.sql:
        return {"target": "database", "requirement_id": requirement.id}
    return {"target": "manual", "requirement_id": requirement.id}


def _success_criteria(
    requirement: RequirementPoint,
    test_types: list[TestCaseType],
) -> list[str]:
    criteria = [f"需求 {requirement.id} 的核心验收点被验证"]
    if requirement.keywords:
        criteria.append("覆盖关键词：" + "、".join(requirement.keywords))
    if TestCaseType.exception in test_types:
        criteria.append("异常路径返回明确错误信息且状态可追踪")
    if TestCaseType.permission in test_types:
        criteria.append("未授权或越权访问被拒绝")
    return criteria


def _risks_for_requirements(
    requirements: list[RequirementPoint],
    context: list[KnowledgeChunk],
) -> list[str]:
    text = " ".join(
        [
            *(_combined_requirement_text(requirement) for requirement in requirements),
            *(chunk.content for chunk in context),
        ]
    ).lower()
    risks: list[str] = []
    if _contains_any(text, ("权限", "角色", "鉴权", "认证", "token", "auth")):
        risks.append("鉴权和权限边界需要重点验证")
    if _contains_any(text, ("幂等", "重复", "冲突", "idempotency")):
        risks.append("重复提交和幂等冲突需要覆盖")
    if _contains_any(text, ("退款", "支付", "金额", "资金")):
        risks.append("资金相关路径需要覆盖异常和审计")
    if _contains_any(text, ("超时", "重试", "队列", "异步")):
        risks.append("异步状态、重试和超时需要覆盖")
    return risks or ["需求存在歧义时需要人工确认验收标准"]


def _combined_requirement_text(requirement: RequirementPoint) -> str:
    return " ".join(
        [
            requirement.id,
            requirement.title,
            requirement.description,
            *requirement.keywords,
            requirement.priority,
        ]
    )


def _keywords_from_text(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_/-]*|[\u4e00-\u9fff]{2,}", text)
    return _dedupe_strings(tokens[:8])


def _short_title(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    return cleaned[:40] or "需求"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _unique_sources(context: list[KnowledgeChunk]) -> list[str]:
    return _dedupe_strings([chunk.source for chunk in context if chunk.source])


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value.strip())
    return result


def _dedupe_test_types(values: list[TestCaseType]) -> list[TestCaseType]:
    result: list[TestCaseType] = []
    seen: set[TestCaseType] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _plan_from_llm_payload(
    payload: dict,
    request: TestPlanGenerationRequest,
) -> TestPlan:
    if not isinstance(payload, dict):
        raise TestPlanOutputValidationError("LLM test plan output must be a JSON object.")
    try:
        return TestPlan(
            id=_stable_id("plan", request.source or request.description),
            title=str(payload.get("title") or _plan_title(request)).strip(),
            source=request.source,
            requirements=request.requirements,
            scope=TestPlanScope.model_validate(payload.get("scope") or {}),
            steps=[
                TestPlanStep.model_validate(step)
                for step in payload.get("steps") or []
            ][: request.max_steps],
        )
    except (TypeError, ValidationError) as exc:
        raise TestPlanOutputValidationError(
            f"LLM test plan output does not match schema: {exc}"
        ) from exc
