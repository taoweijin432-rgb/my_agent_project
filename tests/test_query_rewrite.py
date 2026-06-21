from app.models.test_case import GenerateRequest, TestCaseType as CaseType
from app.services.agent_workflow import analyze_requirement
from app.services.query_rewrite import rewrite_knowledge_query


def test_rewrite_knowledge_query_expands_default_test_terms() -> None:
    request = GenerateRequest(description="生成手机号登录测试用例")
    analysis = analyze_requirement(request)

    query = rewrite_knowledge_query(request, analysis)

    assert "生成手机号登录测试用例" in query
    assert "检索补充关键词" in query
    assert "PRD" in query
    assert "边界值" in query
    assert "权限" in query


def test_rewrite_knowledge_query_uses_focus_and_detected_risk_terms() -> None:
    request = GenerateRequest(
        description="JWT 登录需要防注入并关注并发性能",
        focus_types=[CaseType.security],
    )
    analysis = analyze_requirement(request)

    query = rewrite_knowledge_query(request, analysis)

    assert "JWT" in query
    assert "注入" in query
    assert "安全" in query
    assert "响应时间" not in query
    assert "超时" not in query
