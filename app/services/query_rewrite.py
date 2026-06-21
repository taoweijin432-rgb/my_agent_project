from app.models.test_case import GenerateRequest, TestCaseType
from app.services.agent_workflow import RequirementAnalysis


TYPE_QUERY_TERMS = {
    TestCaseType.functional: ("正常流程", "核心功能", "业务规则"),
    TestCaseType.boundary: ("边界值", "等价类", "输入限制"),
    TestCaseType.exception: ("异常流", "错误处理", "失败场景"),
    TestCaseType.permission: ("权限", "越权", "角色", "访问控制"),
    TestCaseType.compatibility: ("兼容性", "浏览器", "移动端", "系统版本"),
    TestCaseType.performance: ("性能", "并发", "响应时间", "超时"),
    TestCaseType.security: ("安全", "Token", "JWT", "注入", "加密"),
}

BASE_QUERY_TERMS = ("PRD", "接口文档", "验收标准", "测试规范", "历史缺陷")


def rewrite_knowledge_query(
    request: GenerateRequest,
    analysis: RequirementAnalysis,
) -> str:
    target_types = analysis.user_focus_types or [
        TestCaseType.functional,
        TestCaseType.boundary,
        TestCaseType.exception,
        TestCaseType.permission,
        *analysis.detected_risk_types,
    ]
    terms = _unique_terms(
        [
            *BASE_QUERY_TERMS,
            *(term for case_type in target_types for term in TYPE_QUERY_TERMS[case_type]),
        ]
    )
    return (
        f"{request.description.strip()}\n"
        f"检索补充关键词：{' '.join(terms)}"
    )


def _unique_terms(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
