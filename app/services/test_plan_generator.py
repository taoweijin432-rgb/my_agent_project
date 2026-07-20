import hashlib
import re
import threading
from typing import Any, Protocol

from pydantic import ValidationError

from app.core.config import Settings
from app.models.test_case import KnowledgeChunk, RequirementPoint, TestCaseType
from app.models.test_plan import (
    HTTPToolArgs,
    PytestToolArgs,
    TestPlan,
    TestPlanGenerationRequest,
    TestPlanPriority,
    TestPlanScope,
    TestPlanStep,
    TestToolType,
)
from app.services.llm import LLMError
from app.services.prompt import build_test_plan_messages


class TestPlanOutputValidationError(RuntimeError):
    __test__ = False

    pass


LLM_HTTP_HEADER_ALLOWLIST = {"accept", "content-type", "x-request-id"}


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


class TestPlanLLMClient(Protocol):
    settings: Settings

    def generate_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        pass


class LLMTestPlanGenerator:
    def __init__(
        self,
        llm: TestPlanLLMClient,
        *,
        fallback: TestPlanGenerator | None = None,
        allow_fallback: bool = True,
    ):
        self.llm = llm
        self.fallback = fallback or TestPlanGenerator()
        self.allow_fallback = allow_fallback
        self._local = threading.local()
        self.last_used_fallback = False

    @property
    def last_used_fallback(self) -> bool:
        return bool(getattr(self._local, "last_used_fallback", False))

    @last_used_fallback.setter
    def last_used_fallback(self, value: bool) -> None:
        self._local.last_used_fallback = value

    def generate(self, request: TestPlanGenerationRequest) -> TestPlan:
        self.last_used_fallback = False
        try:
            payload = self.llm.generate_json(build_test_plan_messages(request))
            plan = _plan_from_llm_payload(payload, request)
            _validate_generated_plan(plan, request)
            return plan
        except (LLMError, TestPlanOutputValidationError):
            if self.allow_fallback:
                self.last_used_fallback = True
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
    if _looks_like_pytest_text(text):
        return TestToolType.pytest
    if _contains_any(text, ("页面", "浏览器", "按钮", "表单", "ui", "web")):
        return TestToolType.playwright
    if _contains_any(text, ("api", "接口", "http", "post ", "get ", "put ", "delete ")):
        return TestToolType.http
    if _contains_any(text, ("sql", "mysql", "数据库", "表", "字段")):
        return TestToolType.sql
    return TestToolType.manual


def _tool_args_for_requirement(
    requirement: RequirementPoint,
    tool: TestToolType,
) -> dict[str, str | int]:
    if tool == TestToolType.http:
        return _http_tool_args_for_requirement(requirement)
    if tool == TestToolType.pytest:
        return _pytest_tool_args_for_requirement(requirement)
    if tool == TestToolType.playwright:
        return {"target": "ui", "requirement_id": requirement.id}
    if tool == TestToolType.sql:
        return {"target": "database", "requirement_id": requirement.id}
    return {"target": "manual", "requirement_id": requirement.id}


def _http_tool_args_for_requirement(requirement: RequirementPoint) -> dict[str, Any]:
    text = _combined_requirement_text(requirement)
    match = re.search(
        r"\b(GET|POST|PUT|PATCH|DELETE|HEAD)\s+(/[A-Za-z0-9_./{}:-]+)",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return {"endpoint_hint": requirement.id}

    args: dict[str, Any] = {
        "method": match.group(1).upper(),
        "path": match.group(2),
    }
    status_match = re.search(r"\b([1-5][0-9]{2})\b", text)
    if status_match is not None:
        args["expected_status"] = int(status_match.group(1))
    json_assertions = _json_assertions_for_requirement(requirement)
    if json_assertions:
        args["json_assertions"] = json_assertions
    return args


def _json_assertions_for_requirement(requirement: RequirementPoint) -> list[dict[str, Any]]:
    text = _combined_requirement_text(requirement)
    pattern = re.compile(
        r"(?:json\s*)?(?:字段|field)\s+([A-Za-z0-9_.-]+)\s*"
        r"(?:应为|应该为|等于|=|should be|equals)\s*"
        r"([A-Za-z0-9_.:/-]+)",
        flags=re.IGNORECASE,
    )
    assertions: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        path = match.group(1).strip()
        expected = match.group(2).strip().strip("。；;，,")
        if path and expected:
            assertions.append({"path": path, "operator": "equals", "expected": expected})
    return assertions


def _pytest_tool_args_for_requirement(
    requirement: RequirementPoint,
) -> dict[str, str | int]:
    text = _combined_requirement_text(requirement)
    match = re.search(r"\btests/[A-Za-z0-9_./-]+\.py\b", text)
    return {
        "test_path": match.group(0) if match else "tests",
        "maxfail": 1,
    }


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


def _looks_like_pytest_text(text: str) -> bool:
    return _contains_any(text, ("pytest", "py.test")) or re.search(
        r"\btests/[A-Za-z0-9_./-]+\.py\b",
        text,
    ) is not None


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
    payload: dict[str, Any],
    request: TestPlanGenerationRequest,
) -> TestPlan:
    if not isinstance(payload, dict):
        raise TestPlanOutputValidationError("LLM test plan output must be a JSON object.")
    try:
        steps = _llm_steps_from_payload(payload.get("steps"), request)
        if not steps:
            raise TestPlanOutputValidationError("LLM test plan output must include steps.")
        return TestPlan(
            id=_stable_id("plan", request.source or request.description),
            title=str(payload.get("title") or _plan_title(request)).strip(),
            source=request.source,
            requirements=request.requirements,
            scope=_llm_scope_from_payload(payload.get("scope"), request),
            steps=steps,
        )
    except (TypeError, ValidationError, ValueError) as exc:
        raise TestPlanOutputValidationError(
            f"LLM test plan output does not match schema: {exc}"
        ) from exc


def _validate_generated_plan(
    plan: TestPlan,
    request: TestPlanGenerationRequest,
) -> None:
    if not plan.steps:
        raise TestPlanOutputValidationError("LLM test plan validation failed: no steps.")
    _validate_unique_step_ids(plan)
    _validate_requirement_coverage(plan, request)
    _validate_tool_args_contract(plan)


def _validate_unique_step_ids(plan: TestPlan) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for step in plan.steps:
        if step.id in seen:
            duplicates.append(step.id)
        seen.add(step.id)
    if duplicates:
        duplicate_text = ", ".join(_dedupe_strings(duplicates))
        raise TestPlanOutputValidationError(
            f"LLM test plan validation failed: duplicate step ids: {duplicate_text}."
        )


def _validate_requirement_coverage(
    plan: TestPlan,
    request: TestPlanGenerationRequest,
) -> None:
    expected_requirement_ids = [
        requirement.id
        for requirement in request.requirements[: request.max_steps]
        if requirement.id
    ]
    if not expected_requirement_ids:
        return

    covered_requirement_ids = {
        requirement_id
        for step in plan.steps
        for requirement_id in step.requirement_ids
    }
    missing_requirement_ids = [
        requirement_id
        for requirement_id in expected_requirement_ids
        if requirement_id not in covered_requirement_ids
    ]
    if missing_requirement_ids:
        missing_text = ", ".join(missing_requirement_ids)
        raise TestPlanOutputValidationError(
            "LLM test plan validation failed: "
            f"missing requirement coverage for {missing_text}."
        )


def _validate_tool_args_contract(plan: TestPlan) -> None:
    for step in plan.steps:
        try:
            if step.tool == TestToolType.http:
                HTTPToolArgs.model_validate(step.tool_args)
            elif step.tool == TestToolType.pytest:
                PytestToolArgs.model_validate(step.tool_args)
        except (ValidationError, ValueError) as exc:
            raise TestPlanOutputValidationError(
                "LLM test plan validation failed: "
                f"step {step.id} has invalid {step.tool.value} tool_args: {exc}"
            ) from exc


def _llm_scope_from_payload(
    scope: Any,
    request: TestPlanGenerationRequest,
) -> TestPlanScope:
    data = scope if isinstance(scope, dict) else {}
    requirements = request.requirements or [_requirement_from_description(request)]
    normalized = {
        "in_scope": _string_list(data.get("in_scope"))
        or [requirement.title for requirement in requirements],
        "out_of_scope": _string_list(data.get("out_of_scope")),
        "assumptions": _string_list(data.get("assumptions")),
        "risks": _dedupe_strings(
            [
                *_string_list(data.get("risks")),
                *_risks_for_requirements(requirements, request.context),
            ]
        ),
    }
    return TestPlanScope.model_validate(normalized)


def _llm_steps_from_payload(
    steps: Any,
    request: TestPlanGenerationRequest,
) -> list[TestPlanStep]:
    if not isinstance(steps, list):
        raise TestPlanOutputValidationError("LLM test plan steps must be a JSON array.")
    raw_steps = [step for step in steps if isinstance(step, dict)]
    selected = _select_llm_step_payloads(raw_steps, request)
    return [
        TestPlanStep.model_validate(_normalize_llm_step_payload(step, requirement, index))
        for index, (step, requirement) in enumerate(selected, start=1)
    ][: request.max_steps]


def _select_llm_step_payloads(
    raw_steps: list[dict[str, Any]],
    request: TestPlanGenerationRequest,
) -> list[tuple[dict[str, Any], RequirementPoint | None]]:
    if not request.requirements:
        return [(step, None) for step in raw_steps[: request.max_steps]]

    remaining = list(raw_steps)
    selected: list[tuple[dict[str, Any], RequirementPoint | None]] = []
    for requirement in request.requirements[: request.max_steps]:
        index = _find_llm_step_for_requirement(remaining, requirement.id)
        if index is None and remaining:
            index = 0
        if index is None:
            continue
        selected.append((remaining.pop(index), requirement))
    return selected


def _find_llm_step_for_requirement(
    steps: list[dict[str, Any]],
    requirement_id: str,
) -> int | None:
    for index, step in enumerate(steps):
        if requirement_id in _string_list(step.get("requirement_ids")):
            return index
    return None


def _normalize_llm_step_payload(
    step: dict[str, Any],
    requirement: RequirementPoint | None,
    index: int,
) -> dict[str, Any]:
    inferred_text = _combined_requirement_text(requirement) if requirement else ""
    inferred_tool = _tool_for_text(inferred_text) if requirement else TestToolType.manual
    raw_tool = _tool_from_value(step.get("tool"))
    tool = inferred_tool if requirement and inferred_tool != TestToolType.manual else raw_tool
    llm_test_types = _test_types_from_values(step.get("test_types"))
    inferred_test_types = _test_types_for_text(inferred_text) if requirement else []
    test_types = (
        _dedupe_test_types(inferred_test_types)
        if requirement and inferred_test_types
        else _dedupe_test_types(llm_test_types)
    ) or [TestCaseType.functional]
    requirement_ids = [requirement.id] if requirement else _string_list(step.get("requirement_ids"))
    priority = _priority_from_value(
        step.get("priority") or (requirement.priority if requirement else None)
    )
    success_criteria = _dedupe_strings(
        [
            *_string_list(step.get("success_criteria")),
            *(_success_criteria(requirement, test_types) if requirement else []),
        ]
    )

    return {
        "id": f"TP-{index:03d}",
        "title": str(
            step.get("title")
            or (f"验证{requirement.title}" if requirement else f"测试步骤 {index}")
        ).strip(),
        "objective": str(
            step.get("objective")
            or (requirement.description if requirement else step.get("title", "执行测试步骤"))
        ).strip(),
        "requirement_ids": requirement_ids,
        "test_types": test_types,
        "priority": priority,
        "tool": tool,
        "tool_args": _normalize_llm_tool_args(step.get("tool_args"), requirement, tool),
        "success_criteria": success_criteria or ["步骤结果满足验收断言"],
    }


def _normalize_llm_tool_args(
    tool_args: Any,
    requirement: RequirementPoint | None,
    tool: TestToolType,
) -> dict[str, Any]:
    raw = tool_args if isinstance(tool_args, dict) else {}
    if tool == TestToolType.http:
        return _normalize_llm_http_tool_args(raw, requirement)
    if tool == TestToolType.pytest:
        return _normalize_llm_pytest_tool_args(raw, requirement)
    if raw:
        return raw
    if requirement:
        return {"requirement_id": requirement.id}
    return {}


def _normalize_llm_http_tool_args(
    raw: dict[str, Any],
    requirement: RequirementPoint | None,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in (
        "method",
        "path",
        "endpoint_hint",
        "headers",
        "json",
        "expected_status",
        "json_assertions",
    ):
        if key in raw:
            normalized[key] = raw[key]
    if "expected_status" not in normalized and "expected_status_code" in raw:
        normalized["expected_status"] = raw["expected_status_code"]
    if "path" not in normalized and "url" in raw:
        normalized["path"] = raw["url"]

    if requirement is not None:
        requirement_args = _http_tool_args_for_requirement(requirement)
        for key in ("method", "path", "expected_status", "json_assertions"):
            if key in requirement_args:
                normalized[key] = requirement_args[key]
        if "endpoint_hint" in requirement_args and not (
            normalized.get("path") or normalized.get("endpoint_hint")
        ):
            normalized["endpoint_hint"] = requirement_args["endpoint_hint"]

    if "headers" in normalized:
        normalized["headers"] = _allowed_llm_http_headers(normalized["headers"])

    args = HTTPToolArgs.model_validate(normalized)
    result: dict[str, Any] = {
        "method": args.resolved_method,
        "path": args.resolved_path,
        "expected_status": args.expected_status,
    }
    if args.headers:
        result["headers"] = args.headers
    if args.json_body is not None:
        result["json"] = args.json_body
    if args.json_assertions:
        result["json_assertions"] = [
            assertion.model_dump(mode="json") for assertion in args.json_assertions
        ]
    return result


def _normalize_llm_pytest_tool_args(
    raw: dict[str, Any],
    requirement: RequirementPoint | None,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        key: raw[key]
        for key in ("test_path", "path", "keyword", "marker", "maxfail")
        if key in raw
    }
    if requirement is not None:
        requirement_args = _pytest_tool_args_for_requirement(requirement)
        if "test_path" not in normalized and "path" not in normalized:
            normalized["test_path"] = requirement_args["test_path"]
        if "maxfail" not in normalized:
            normalized["maxfail"] = requirement_args["maxfail"]
    return normalized


def _allowed_llm_http_headers(headers: Any) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in headers.items():
        name = str(key).strip()
        normalized_name = name.lower()
        text = str(value).strip()
        if normalized_name not in LLM_HTTP_HEADER_ALLOWLIST:
            continue
        if _invalid_llm_http_header_value(normalized_name, text):
            continue
        result[name] = text
    return result


def _invalid_llm_http_header_value(name: str, value: str) -> bool:
    if not value:
        return True
    if name not in {"accept", "content-type"}:
        return False
    media_type = value.split(";", 1)[0].strip()
    return (
        "/" not in media_type
        or media_type.startswith("/")
        or media_type.endswith("/")
    )


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _test_types_from_values(value: Any) -> list[TestCaseType]:
    result: list[TestCaseType] = []
    for item in _string_list(value):
        try:
            result.append(TestCaseType(item))
        except ValueError:
            continue
    return result


def _priority_from_value(value: Any) -> TestPlanPriority:
    try:
        return TestPlanPriority(str(value or TestPlanPriority.medium.value))
    except ValueError:
        return TestPlanPriority.medium


def _tool_from_value(value: Any) -> TestToolType:
    try:
        return TestToolType(str(value or TestToolType.manual.value))
    except ValueError:
        return TestToolType.manual
