import pytest

from app.api import routes
from app.models.test_case import (
    KnowledgeDocumentSummary,
    KnowledgeDocumentUpsertRequest,
)


class FakeRagService:
    def __init__(self):
        self.upserts = []
        self.deleted_sources = []
        self.documents = [
            KnowledgeDocumentSummary(
                source="knowledge/prd/login.md",
                document_type="prd",
                module="login",
                tags=["prd", "login"],
                version=2,
                chunk_count=3,
                content_hash="hash-value",
                updated_at="2026-06-21T00:00:00+00:00",
            )
        ]

    def list_documents(self, *, limit=100, offset=0):
        return self.documents[offset : offset + limit], len(self.documents)

    def upsert_document(self, document, *, chunk_size):
        self.upserts.append((document, chunk_size))
        return 2, 3, 3

    def delete_document(self, source):
        self.deleted_sources.append(source)
        return 3


@pytest.fixture
def fake_rag(monkeypatch) -> FakeRagService:
    service = FakeRagService()
    monkeypatch.setattr(routes, "_rag_service", lambda: service)
    return service


def test_list_knowledge_documents(fake_rag) -> None:
    response = routes.list_knowledge_documents(limit=10, offset=0)

    assert response.total == 1
    assert response.documents[0].source == "knowledge/prd/login.md"
    assert response.documents[0].version == 2
    assert response.documents[0].chunk_count == 3


def test_upsert_knowledge_document(fake_rag) -> None:
    response = routes.upsert_knowledge_document(
        KnowledgeDocumentUpsertRequest.model_validate(
            {
                "document": {
                    "source": "knowledge/prd/login.md",
                    "content": "账号密码登录规则",
                    "document_type": "prd",
                    "module": "login",
                    "tags": ["prd", "login"],
                },
                "chunk_size": 500,
            }
        )
    )

    assert response.model_dump() == {
        "source": "knowledge/prd/login.md",
        "version": 3,
        "added_chunks": 2,
        "replaced_chunks": 3,
    }
    assert fake_rag.upserts[0][0].source == "knowledge/prd/login.md"
    assert fake_rag.upserts[0][1] == 500


def test_delete_knowledge_document(fake_rag) -> None:
    response = routes.delete_knowledge_document(source="knowledge/prd/login.md")

    assert response.model_dump() == {
        "source": "knowledge/prd/login.md",
        "deleted_chunks": 3,
    }
    assert fake_rag.deleted_sources == ["knowledge/prd/login.md"]
