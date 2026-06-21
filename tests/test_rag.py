import sys
import types

import numpy as np
import pytest

from app.core.config import Settings
from app.models.test_case import KnowledgeDocument
from app.services.rag import (
    ChromaUnavailableError,
    HashEmbeddingFunction,
    RagService,
    SentenceTransformerEmbeddingFunction,
    _build_embedding_function,
)


def test_build_embedding_function_defaults_to_hash() -> None:
    embedding = _build_embedding_function(Settings())

    assert isinstance(embedding, HashEmbeddingFunction)


def test_build_embedding_function_rejects_unknown_provider() -> None:
    settings = Settings(embedding_provider="unknown")

    with pytest.raises(ChromaUnavailableError):
        _build_embedding_function(settings)


def test_sentence_transformer_embedding_function_uses_configured_cache(
    monkeypatch,
    tmp_path,
) -> None:
    created = {}

    class FakeSentenceTransformer:
        def __init__(self, model_name, cache_folder, device, local_files_only):
            created["model_name"] = model_name
            created["cache_folder"] = cache_folder
            created["device"] = device
            created["local_files_only"] = local_files_only

        def encode(self, input, normalize_embeddings, convert_to_numpy):
            return np.ones((len(input), 3), dtype=float)

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )

    embedding = SentenceTransformerEmbeddingFunction(
        "fake-model",
        cache_dir=str(tmp_path / "hf-cache"),
        device="cpu",
        local_files_only=True,
    )

    assert created["model_name"] == "fake-model"
    assert created["cache_folder"] == str(tmp_path / "hf-cache")
    assert created["device"] == "cpu"
    assert created["local_files_only"] is True
    assert embedding(["需求", "用例"]) == [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]


def test_rag_service_ingests_and_searches_with_hash_embedding(tmp_path) -> None:
    settings = Settings(
        chroma_path=str(tmp_path / "chroma"),
        chroma_collection="test_knowledge_hash",
        embedding_provider="hash",
    )
    service = RagService(settings)

    added = service.ingest_documents(
        [
            KnowledgeDocument(
                source="login-prd.md",
                content="手机号验证码登录，验证码 6 位数字，5 分钟有效。",
                document_type="prd",
                module="login",
                tags=["prd", "login"],
            ),
            KnowledgeDocument(
                source="order-prd.md",
                content="订单支付成功后生成支付流水，并通知库存系统。",
                document_type="prd",
                module="order",
                tags=["prd", "order"],
            ),
        ]
    )
    chunks = service.search("验证码登录", top_k=1)

    assert added == 2
    assert len(chunks) == 1
    assert chunks[0].content
    assert chunks[0].source in {"login-prd.md", "order-prd.md"}
    assert chunks[0].document_type == "prd"
    assert chunks[0].module in {"login", "order"}
    assert "prd" in chunks[0].tags
