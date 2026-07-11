from app.models.test_case import KnowledgeChunk
from scripts.evaluate_rag import build_gap_report, evaluate_case, evaluate_cases, summarize_results


def test_evaluate_case_matches_sources_and_keywords() -> None:
    case = {
        "id": "auth",
        "query": "JWT 登录",
        "expected_sources": ["knowledge_export/api/auth_permissions.md"],
        "expected_keywords": ["JWT", "refresh"],
    }
    chunks = [
        KnowledgeChunk(
            content="JWT login and refresh token",
            source="knowledge_export\\api\\auth_permissions.md",
            score=0.8,
            document_type="api",
            module="auth_permissions",
            chunk=1,
            tags=["api", "auth_permissions"],
        )
    ]

    result = evaluate_case(case, chunks)

    assert result["source_pass"] is True
    assert result["keyword_pass"] is True
    assert result["case_pass"] is True
    assert result["matched_sources"] == ["knowledge_export/api/auth_permissions.md"]
    assert result["matched_keywords"] == ["JWT", "refresh"]


def test_evaluate_case_fails_when_source_is_missing() -> None:
    case = {
        "id": "auth",
        "query": "JWT 登录",
        "expected_sources": ["knowledge_export/api/auth_permissions.md"],
        "expected_keywords": ["JWT"],
    }
    chunks = [
        KnowledgeChunk(
            content="JWT login",
            source="knowledge_export/api/questionnaire.md",
            score=0.1,
        )
    ]

    result = evaluate_case(case, chunks)

    assert result["source_pass"] is False
    assert result["keyword_pass"] is True
    assert result["case_pass"] is False


def test_evaluate_cases_and_summary() -> None:
    cases = [
        {
            "id": "pass",
            "query": "登录",
            "expected_sources": ["auth.md"],
            "expected_keywords": ["JWT"],
        },
        {
            "id": "fail",
            "query": "问卷",
            "expected_sources": ["questionnaire.md"],
            "expected_keywords": ["问卷"],
        },
    ]

    def search_fn(query: str, top_k: int) -> list[KnowledgeChunk]:
        if query == "登录":
            return [KnowledgeChunk(content="JWT", source="auth.md")]
        return [KnowledgeChunk(content="无关", source="other.md")]

    results = evaluate_cases(cases, search_fn=search_fn, top_k=3)
    summary = summarize_results(results)

    assert summary["cases"] == 2
    assert summary["source_hits"] == 1
    assert summary["source_hit_rate"] == 0.5
    assert summary["keyword_hits"] == 1
    assert summary["keyword_total"] == 2
    assert summary["keyword_hit_rate"] == 0.5
    assert summary["case_passes"] == 1
    assert summary["source_stats"] == [
        {
            "source": "questionnaire.md",
            "expected_cases": 1,
            "source_hits": 0,
            "hit_rate": 0.0,
        },
        {
            "source": "auth.md",
            "expected_cases": 1,
            "source_hits": 1,
            "hit_rate": 1.0,
        },
    ]


def test_build_gap_report_lists_missing_sources_and_keywords() -> None:
    case = {
        "id": "refund-gap",
        "query": "退款 风控 审计",
        "expected_sources": ["knowledge/risk/refund/refund-risk-rules.md"],
        "expected_keywords": ["large_amount_refund", "risk_flags"],
    }
    chunks = [
        KnowledgeChunk(
            content="退款审计日志包含 request_id",
            source="knowledge/audit/refund/refund-audit-log.md",
            score=0.42,
            document_type="audit",
            module="refund",
            chunk=0,
            tags=["audit", "refund"],
        )
    ]
    result = evaluate_case(case, chunks, case_keyword_ratio=1.0)
    summary = summarize_results([result])

    report = build_gap_report(summary, [result])

    assert "# RAG Gap Report" in report
    assert "### refund-gap" in report
    assert "missing_sources: knowledge/risk/refund/refund-risk-rules.md" in report
    assert "missing_keywords: large_amount_refund, risk_flags" in report
    assert "### refund-gap 补充知识" in report


def test_build_gap_report_handles_no_gaps() -> None:
    case = {
        "id": "pass",
        "query": "JWT 登录",
        "expected_sources": ["auth.md"],
        "expected_keywords": ["JWT"],
    }
    result = evaluate_case(case, [KnowledgeChunk(content="JWT", source="auth.md")])
    summary = summarize_results([result])

    report = build_gap_report(summary, [result])

    assert "gap_cases: 0" in report
    assert "No retrieval gaps found." in report
