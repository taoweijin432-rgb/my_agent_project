import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.api.routes import require_api_key
from app.main import app
from app.models.test_case import KnowledgeDocumentSummary


client = TestClient(app)


@pytest.fixture(autouse=True)
def bypass_api_key() -> None:
    app.dependency_overrides[require_api_key] = lambda: None
    yield
    app.dependency_overrides.pop(require_api_key, None)


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
    response = client.get("/api/v1/knowledge/documents?limit=10&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["documents"][0]["source"] == "knowledge/prd/login.md"
    assert payload["documents"][0]["version"] == 2
    assert payload["documents"][0]["chunk_count"] == 3


def test_upsert_knowledge_document(fake_rag) -> None:
    response = client.post(
        "/api/v1/knowledge/documents/upsert",
        json={
            "document": {
                "source": "knowledge/prd/login.md",
                "content": "账号密码登录规则",
                "document_type": "prd",
                "module": "login",
                "tags": ["prd", "login"],
            },
            "chunk_size": 500,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "source": "knowledge/prd/login.md",
        "version": 3,
        "added_chunks": 2,
        "replaced_chunks": 3,
    }
    assert fake_rag.upserts[0][0].source == "knowledge/prd/login.md"
    assert fake_rag.upserts[0][1] == 500


def test_delete_knowledge_document(fake_rag) -> None:
    response = client.delete(
        "/api/v1/knowledge/documents",
        params={"source": "knowledge/prd/login.md"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "source": "knowledge/prd/login.md",
        "deleted_chunks": 3,
    }
    assert fake_rag.deleted_sources == ["knowledge/prd/login.md"]
