from app.api import routes
from app.models.test_case import CoverageEvaluationRequest, CoverageGapKnowledgeRequest
from app.services.coverage import (
    build_coverage_gap_knowledge_document,
    evaluate_requirement_coverage,
)


CASE_SUCCESS = {
    "id": "TC-001",
    "title": "手机号验证码登录成功",
    "precondition": "用户已注册，验证码未过期。",
    "steps": ["输入手机号", "输入 6 位验证码", "点击登录"],
    "expected": ["登录成功", "进入系统首页"],
    "type": "functional",
}
CASE_LOCK = {
    "id": "TC-002",
    "title": "连续 5 次验证码错误后账号锁定",
    "precondition": "用户账号未锁定。",
    "steps": ["连续 5 次输入错误验证码", "再次点击登录"],
    "expected": ["账号锁定 10 分钟", "提示稍后重试"],
    "type": "exception",
}
REQUIREMENTS = [
    {
        "id": "REQ-001",
        "title": "验证码登录成功",
        "keywords": ["验证码", "登录成功"],
        "priority": "high",
    },
    {
        "id": "REQ-002",
        "title": "错误次数锁定",
        "keywords": ["5 次", "锁定", "10 分钟"],
        "priority": "critical",
    },
    {
        "id": "REQ-003",
        "title": "验证码过期",
        "keywords": ["5 分钟", "过期"],
        "priority": "medium",
    },
]


def test_evaluate_requirement_coverage_flags_uncovered_points() -> None:
    request = CoverageEvaluationRequest.model_validate(
        {
            "requirements": REQUIREMENTS,
            "cases": [CASE_SUCCESS, CASE_LOCK],
            "min_keyword_match_ratio": 1.0,
        }
    )

    report = evaluate_requirement_coverage(request)

    assert report.total_requirements == 3
    assert report.covered_requirements == 2
    assert report.coverage_rate == 0.6667
    assert report.uncovered_requirement_ids == ["REQ-003"]
    assert report.items[0].matched_case_ids == ["TC-001"]
    assert report.items[1].matched_case_ids == ["TC-002"]
    assert report.items[2].missing_keywords == ["5 分钟", "过期"]
    assert "uncovered_requirements" in report.warnings


def test_build_coverage_gap_knowledge_document_uses_uncovered_items_only() -> None:
    report = evaluate_requirement_coverage(
        CoverageEvaluationRequest.model_validate(
            {
                "requirements": REQUIREMENTS,
                "cases": [CASE_SUCCESS, CASE_LOCK],
                "min_keyword_match_ratio": 1.0,
            }
        )
    )

    document, gap_count = build_coverage_gap_knowledge_document(
        CoverageGapKnowledgeRequest(
            coverage=report,
            source="knowledge/evaluation/login-coverage-gaps.md",
            module="login",
            tags=["manual"],
        )
    )

    assert gap_count == 1
    assert document.source == "knowledge/evaluation/login-coverage-gaps.md"
    assert document.document_type == "evaluation"
    assert document.module == "login"
    assert document.tags == ["manual", "login", "coverage-gap", "human-confirmed"]
    assert "REQ-003 验证码过期" in document.content
    assert "缺失关键词：5 分钟、过期" in document.content
    assert "REQ-001 验证码登录成功" not in document.content


def test_upsert_coverage_gap_knowledge_route_uses_rag_upsert(monkeypatch) -> None:
    class FakeRagService:
        def __init__(self) -> None:
            self.upserts = []

        def upsert_document(self, document, *, chunk_size):
            self.upserts.append((document, chunk_size))
            return 1, 0, 2

    service = FakeRagService()
    monkeypatch.setattr(routes, "_rag_service", lambda: service)
    report = evaluate_requirement_coverage(
        CoverageEvaluationRequest.model_validate(
            {
                "requirements": REQUIREMENTS,
                "cases": [CASE_SUCCESS, CASE_LOCK],
                "min_keyword_match_ratio": 1.0,
            }
        )
    )

    response = routes.upsert_coverage_gap_knowledge(
        CoverageGapKnowledgeRequest(
            coverage=report,
            source="knowledge/evaluation/login-coverage-gaps.md",
            module="login",
            chunk_size=500,
        )
    )

    assert response.source == "knowledge/evaluation/login-coverage-gaps.md"
    assert response.version == 2
    assert response.gap_count == 1
    assert service.upserts[0][0].source == "knowledge/evaluation/login-coverage-gaps.md"
    assert service.upserts[0][1] == 500
