from app.models.test_case import KnowledgeChunk
from scripts.evaluate_rag import evaluate_case, evaluate_cases, summarize_results


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
