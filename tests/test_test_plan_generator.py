import json
from pathlib import Path

from app.models.test_case import KnowledgeChunk, RequirementPoint
from app.models.test_case import TestCaseType as CaseType
from app.models.test_plan import TestPlanGenerationRequest as PlanRequest
from app.models.test_plan import TestToolType as ToolType
from app.services.llm import LLMError
from app.services.test_plan_generator import LLMTestPlanGenerator, generate_test_plan


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class FakeLLM:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload or {}
        self.error = error
        self.messages = []

    def generate_json(self, messages):
        self.messages.append(messages)
        if self.error:
            raise self.error
        return self.payload


def test_generate_test_plan_builds_steps_from_requirements() -> None:
    plan = generate_test_plan(
        PlanRequest(
            description="订单退款接口需要支持幂等提交和权限校验。",
            source="knowledge/prd/refund/refund.md",
            requirements=[
                RequirementPoint(
                    id="REFUND-001",
                    title="创建退款 API",
                    description="POST /api/v1/refunds 创建退款，重复 idempotency_key 需要返回冲突。",
                    keywords=["POST /api/v1/refunds", "idempotency_key", "冲突"],
                    priority="critical",
                ),
                RequirementPoint(
                    id="REFUND-002",
                    title="退款权限校验",
                    description="没有退款权限的角色不能创建退款。",
                    keywords=["权限", "角色", "拒绝"],
                    priority="high",
                ),
            ],
            context=[
                KnowledgeChunk(
                    content="退款属于资金路径，需要审计。",
                    source="knowledge/risk/refund/fund-risk.md",
                )
            ],
        )
    )

    assert plan.id.startswith("plan-")
    assert plan.title == "refund.md 测试计划"
    assert [step.id for step in plan.steps] == ["TP-001", "TP-002"]
    assert plan.steps[0].tool == ToolType.http
    assert plan.steps[0].tool_args["method"] == "POST"
    assert plan.steps[0].tool_args["path"] == "/api/v1/refunds"
    assert CaseType.exception in plan.steps[0].test_types
    assert plan.steps[0].priority.value == "critical"
    assert plan.steps[1].tool == ToolType.manual
    assert CaseType.permission in plan.steps[1].test_types
    assert "参考知识来源：knowledge/risk/refund/fund-risk.md" in plan.scope.assumptions
    assert "资金相关路径需要覆盖异常和审计" in plan.scope.risks


def test_generate_test_plan_extracts_http_expected_status() -> None:
    plan = generate_test_plan(
        PlanRequest(
            description="退款接口需要返回创建状态。",
            requirements=[
                RequirementPoint(
                    id="REFUND-201",
                    title="创建退款 API",
                    description="POST /api/v1/refunds 返回 201。",
                    keywords=["POST /api/v1/refunds", "201"],
                    priority="critical",
                )
            ],
        )
    )

    assert plan.steps[0].tool == ToolType.http
    assert plan.steps[0].tool_args == {
        "method": "POST",
        "path": "/api/v1/refunds",
        "expected_status": 201,
    }


def test_generate_test_plan_extracts_http_json_assertions() -> None:
    plan = generate_test_plan(
        PlanRequest(
            description="退款金额对账需要校验响应字段。",
            requirements=[
                RequirementPoint(
                    id="REFUND-AMOUNT-001",
                    title="退款金额对账 API",
                    description=(
                        "GET /api/v1/refunds/rf_001/reconciliation 返回 200，"
                        "JSON 字段 amount 应为 100.00。"
                    ),
                    keywords=["GET /api/v1/refunds/rf_001/reconciliation", "amount"],
                    priority="critical",
                )
            ],
        )
    )

    assert plan.steps[0].tool == ToolType.http
    assert plan.steps[0].tool_args == {
        "method": "GET",
        "path": "/api/v1/refunds/rf_001/reconciliation",
        "expected_status": 200,
        "json_assertions": [
            {"path": "amount", "operator": "equals", "expected": "100.00"}
        ],
    }


def test_generate_test_plan_uses_description_when_requirements_are_absent() -> None:
    plan = generate_test_plan(
        PlanRequest(
            description="登录页面需要支持手机号验证码表单，验证码错误时展示明确错误。",
            max_steps=3,
        )
    )

    assert len(plan.requirements) == 1
    assert plan.requirements[0].id == "REQ-001"
    assert plan.steps[0].tool == ToolType.playwright
    assert CaseType.exception in plan.steps[0].test_types
    assert plan.steps[0].requirement_ids == ["REQ-001"]


def test_generate_test_plan_selects_sql_tool_for_database_requirements() -> None:
    plan = generate_test_plan(
        PlanRequest(
            description="生成数据库校验计划。",
            requirements=[
                RequirementPoint(
                    id="DB-001",
                    title="生成历史落库",
                    description="MySQL generation_records 表需要写入生成状态字段。",
                    keywords=["MySQL", "generation_records", "字段"],
                    priority="medium",
                )
            ],
        )
    )

    assert plan.steps[0].tool == ToolType.sql
    assert plan.steps[0].tool_args == {
        "target": "database",
        "requirement_id": "DB-001",
    }


def test_generate_test_plan_selects_pytest_tool_for_pytest_requirements() -> None:
    plan = generate_test_plan(
        PlanRequest(
            description="生成 pytest 回归计划。",
            requirements=[
                RequirementPoint(
                    id="PYTEST-001",
                    title="报告服务回归",
                    description="运行 pytest tests/test_test_report.py 验证报告断言。",
                    keywords=["pytest", "tests/test_test_report.py", "断言"],
                    priority="high",
                )
            ],
        )
    )

    assert plan.steps[0].tool == ToolType.pytest
    assert plan.steps[0].tool_args == {
        "test_path": "tests/test_test_report.py",
        "maxfail": 1,
    }


def test_llm_test_plan_generator_validates_structured_output() -> None:
    llm = FakeLLM(
        {
            "title": "退款测试计划",
            "scope": {
                "in_scope": ["创建退款"],
                "out_of_scope": ["财务对账"],
                "assumptions": ["测试账号已准备"],
                "risks": ["幂等冲突"],
            },
            "steps": [
                {
                    "id": "TP-001",
                    "title": "验证创建退款幂等冲突",
                    "objective": "重复提交 idempotency_key 时返回冲突",
                    "requirement_ids": ["REFUND-001"],
                    "test_types": ["functional", "exception"],
                    "priority": "critical",
                    "tool": "http",
                    "tool_args": {
                        "target": "api",
                        "endpoint_hint": "POST /api/v1/refunds",
                    },
                    "success_criteria": ["第二次提交返回冲突错误"],
                }
            ],
        }
    )

    plan = LLMTestPlanGenerator(llm).generate(
        PlanRequest(
            description="退款接口需要覆盖幂等冲突。",
            requirements=[
                RequirementPoint(
                    id="REFUND-001",
                    title="创建退款 API",
                    description="POST /api/v1/refunds 创建退款。",
                    keywords=["idempotency_key"],
                    priority="critical",
                )
            ],
        )
    )

    assert plan.title == "退款测试计划"
    assert plan.steps[0].tool == ToolType.http
    assert plan.steps[0].tool_args == {
        "method": "POST",
        "path": "/api/v1/refunds",
        "expected_status": 200,
    }
    assert "结构化需求点" in llm.messages[0][1]["content"]


def test_llm_test_plan_generator_normalizes_http_aliases_from_requirements() -> None:
    llm = FakeLLM(
        {
            "title": "权限测试计划",
            "scope": {
                "in_scope": ["管理员接口"],
                "out_of_scope": [],
                "assumptions": [],
                "risks": [],
            },
            "steps": [
                {
                    "id": "CUSTOM-1",
                    "title": "验证管理员接口权限校验",
                    "objective": "无权限角色访问管理员接口应被拒绝",
                    "requirement_ids": ["AUTH-001"],
                    "test_types": ["permission"],
                    "priority": "critical",
                    "tool": "http",
                    "tool_args": {
                        "target": "api",
                        "endpoint_hint": "/api/v1/admin/{id}",
                        "method": "GET",
                        "expected_status_code": 403,
                        "headers": {"Authorization": "Bearer invalid_token"},
                    },
                    "success_criteria": ["返回 403"],
                }
            ],
        }
    )

    plan = LLMTestPlanGenerator(llm).generate(
        PlanRequest(
            description="管理员接口权限校验。",
            requirements=[
                RequirementPoint(
                    id="AUTH-001",
                    title="管理员接口权限校验",
                    description="无权限角色 GET /api/v1/admin/users 应返回 403，越权访问必须被拒绝。",
                    keywords=["GET /api/v1/admin/users", "403", "越权"],
                    priority="critical",
                )
            ],
        )
    )

    assert plan.steps[0].id == "TP-001"
    assert plan.steps[0].tool_args == {
        "method": "GET",
        "path": "/api/v1/admin/users",
        "expected_status": 403,
    }
    assert CaseType.security in plan.steps[0].test_types
    assert "鉴权和权限边界需要重点验证" in plan.scope.risks


def test_llm_test_plan_generator_filters_invalid_http_header_values() -> None:
    llm = FakeLLM(
        {
            "title": "退款测试计划",
            "steps": [
                {
                    "title": "验证创建退款",
                    "requirement_ids": ["REFUND-001"],
                    "tool": "http",
                    "tool_args": {
                        "method": "POST",
                        "path": "/api/v1/refunds",
                        "expected_status": 201,
                        "headers": {
                            "Accept": "application/",
                            "Content-Type": "application/",
                            "X-Request-ID": "req-001",
                        },
                    },
                }
            ],
        }
    )

    plan = LLMTestPlanGenerator(llm).generate(
        PlanRequest(
            description="创建退款。",
            requirements=[
                RequirementPoint(
                    id="REFUND-001",
                    title="创建退款 API",
                    description="POST /api/v1/refunds 返回 201。",
                    keywords=["POST /api/v1/refunds", "201"],
                )
            ],
        )
    )

    assert plan.steps[0].tool_args == {
        "method": "POST",
        "path": "/api/v1/refunds",
        "expected_status": 201,
        "headers": {"X-Request-ID": "req-001"},
    }


def test_llm_test_plan_generator_preserves_http_json_assertions() -> None:
    llm = FakeLLM(
        {
            "title": "退款金额对账测试计划",
            "steps": [
                {
                    "title": "验证退款金额对账",
                    "requirement_ids": ["REFUND-AMOUNT-001"],
                    "tool": "http",
                    "tool_args": {
                        "method": "GET",
                        "path": "/api/v1/refunds/rf_001/reconciliation",
                        "expected_status": 200,
                        "json_assertions": [
                            {
                                "path": "$.amount",
                                "operator": "equals",
                                "expected": "100.00",
                            }
                        ],
                    },
                }
            ],
        }
    )

    plan = LLMTestPlanGenerator(llm).generate(
        PlanRequest(
            description="退款金额对账。",
            requirements=[
                RequirementPoint(
                    id="REFUND-AMOUNT-001",
                    title="退款金额对账 API",
                    description=(
                        "GET /api/v1/refunds/rf_001/reconciliation 返回 200，"
                        "JSON 字段 amount 应为 100.00。"
                    ),
                    keywords=["GET /api/v1/refunds/rf_001/reconciliation", "amount"],
                )
            ],
        )
    )

    assert plan.steps[0].tool_args == {
        "method": "GET",
        "path": "/api/v1/refunds/rf_001/reconciliation",
        "expected_status": 200,
        "json_assertions": [
            {"path": "amount", "operator": "equals", "expected": "100.00"}
        ],
    }


def test_llm_test_plan_generator_prefers_inferred_test_types_for_requirements() -> None:
    llm = FakeLLM(
        {
            "title": "退款测试计划",
            "steps": [
                {
                    "title": "验证创建退款",
                    "requirement_ids": ["REFUND-001"],
                    "test_types": ["functional", "boundary", "security", "performance"],
                    "tool": "http",
                    "tool_args": {
                        "method": "POST",
                        "path": "/api/v1/refunds",
                        "expected_status": 201,
                    },
                },
                {
                    "title": "验证审计查询失败",
                    "requirement_ids": ["REFUND-002"],
                    "test_types": ["functional", "boundary", "security"],
                    "tool": "http",
                    "tool_args": {
                        "method": "GET",
                        "path": "/api/v1/refunds/rf_001/audit",
                        "expected_status": 200,
                    },
                },
            ],
        }
    )

    plan = LLMTestPlanGenerator(llm).generate(
        PlanRequest(
            description="退款接口需要覆盖创建和失败审计。",
            requirements=[
                RequirementPoint(
                    id="REFUND-001",
                    title="创建退款 API",
                    description="POST /api/v1/refunds 返回 201 并生成退款编号。",
                    keywords=["POST /api/v1/refunds", "201", "refund_id"],
                    priority="critical",
                ),
                RequirementPoint(
                    id="REFUND-002",
                    title="退款审计查询 API",
                    description="GET /api/v1/refunds/rf_001/audit 返回 200；失败时应暴露审计不可用。",
                    keywords=["GET /api/v1/refunds/rf_001/audit", "200", "audit"],
                    priority="high",
                ),
            ],
        )
    )

    assert plan.steps[0].test_types == [CaseType.functional]
    assert plan.steps[1].test_types == [CaseType.functional, CaseType.exception]


def test_llm_test_plan_generator_falls_back_when_llm_fails() -> None:
    plan = LLMTestPlanGenerator(FakeLLM(error=LLMError("upstream failed"))).generate(
        PlanRequest(description="登录页面验证码错误时展示明确错误。")
    )

    assert plan.steps[0].id == "TP-001"
    assert plan.steps[0].tool == ToolType.playwright


def test_test_plan_eval_fixture_matches_rule_based_planner() -> None:
    cases = json.loads((FIXTURES_DIR / "test_plan_eval_cases.json").read_text())

    for case in cases:
        plan = generate_test_plan(
            PlanRequest(
                description=case["description"],
                requirements=[
                    RequirementPoint.model_validate(requirement)
                    for requirement in case["requirements"]
                ],
            )
        )
        tools = {step.tool.value for step in plan.steps}
        test_types = {
            test_type.value
            for step in plan.steps
            for test_type in step.test_types
        }
        risks = " ".join(plan.scope.risks)

        assert set(case["expected"]["tools"]).issubset(tools)
        assert set(case["expected"]["test_types"]).issubset(test_types)
        for keyword in case["expected"]["risk_keywords"]:
            assert keyword in risks
