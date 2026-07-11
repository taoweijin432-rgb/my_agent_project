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
    assert CaseType.exception in plan.steps[0].test_types
    assert plan.steps[0].priority.value == "critical"
    assert plan.steps[1].tool == ToolType.manual
    assert CaseType.permission in plan.steps[1].test_types
    assert "参考知识来源：knowledge/risk/refund/fund-risk.md" in plan.scope.assumptions
    assert "资金相关路径需要覆盖异常和审计" in plan.scope.risks


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
    assert plan.steps[0].tool_args["endpoint_hint"] == "POST /api/v1/refunds"
    assert "结构化需求点" in llm.messages[0][1]["content"]


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
