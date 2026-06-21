import hashlib
import math
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT, Settings
from app.models.test_case import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentSummary


class ChromaUnavailableError(RuntimeError):
    """Raised when ChromaDB is not installed or cannot start."""


class HashEmbeddingFunction:
    """Deterministic local embeddings for Chroma without external downloads."""

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    @staticmethod
    def name() -> str:
        return "local_hash_embedding"

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "HashEmbeddingFunction":
        return HashEmbeddingFunction(dimensions=int(config.get("dimensions", 384)))

    @staticmethod
    def validate_config(config: dict[str, Any]) -> None:
        dimensions = int(config.get("dimensions", 384))
        if dimensions <= 0:
            raise ValueError("dimensions must be greater than 0")

    def get_config(self) -> dict[str, Any]:
        return {"dimensions": self.dimensions}

    def default_space(self) -> str:
        return "cosine"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(item * item for item in vector)) or 1.0
        return [item / norm for item in vector]


class SentenceTransformerEmbeddingFunction:
    """SentenceTransformers embeddings backed by a local Hugging Face cache."""

    def __init__(
        self,
        model_name: str,
        *,
        cache_dir: str,
        device: str = "cpu",
        local_files_only: bool = False,
        normalize_embeddings: bool = True,
    ):
        self.model_name = model_name
        self.cache_dir = str(_resolve_project_path(cache_dir))
        self.device = device
        self.local_files_only = local_files_only
        self.normalize_embeddings = normalize_embeddings
        os.environ.setdefault("HF_HOME", self.cache_dir)
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ChromaUnavailableError(
                "sentence-transformers is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        self.model = SentenceTransformer(
            self.model_name,
            cache_folder=self.cache_dir,
            device=self.device,
            local_files_only=self.local_files_only,
        )

    @staticmethod
    def name() -> str:
        return "sentence_transformers_embedding"

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "SentenceTransformerEmbeddingFunction":
        return SentenceTransformerEmbeddingFunction(
            model_name=str(config.get("model_name", "BAAI/bge-small-zh-v1.5")),
            cache_dir=str(config.get("cache_dir", ".model_cache/huggingface")),
            device=str(config.get("device", "cpu")),
            local_files_only=bool(config.get("local_files_only", False)),
            normalize_embeddings=bool(config.get("normalize_embeddings", True)),
        )

    @staticmethod
    def validate_config(config: dict[str, Any]) -> None:
        if not str(config.get("model_name", "")).strip():
            raise ValueError("model_name must not be empty")

    def get_config(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "cache_dir": self.cache_dir,
            "device": self.device,
            "local_files_only": self.local_files_only,
            "normalize_embeddings": self.normalize_embeddings,
        }

    def default_space(self) -> str:
        return "cosine"

    def __call__(self, input: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(
            input,
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
        )
        return embeddings.tolist()

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)


class RagService:
    def __init__(self, settings: Settings):
        self.settings = settings
        try:
            import chromadb
        except ImportError as exc:
            raise ChromaUnavailableError(
                "chromadb is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        path = Path(settings.chroma_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=_build_embedding_function(settings),
        )

    def ingest_documents(self, documents: list[KnowledgeDocument], chunk_size: int = 900) -> int:
        chunks: list[str] = []
        ids: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for document in documents:
            version = self._next_document_version(document.source)
            for index, chunk in enumerate(_chunk_text(document.content, chunk_size), start=1):
                chunks.append(chunk)
                ids.append(f"{uuid.uuid4()}")
                metadatas.append(
                    _document_metadata(document, index=index, version=version)
                )

        if chunks:
            self.collection.add(ids=ids, documents=chunks, metadatas=metadatas)
        return len(chunks)

    def upsert_document(
        self,
        document: KnowledgeDocument,
        *,
        chunk_size: int = 900,
    ) -> tuple[int, int, int]:
        previous_chunks, next_version = self._delete_existing_for_update(document.source)
        added_chunks = self._add_document_chunks(
            document,
            chunk_size=chunk_size,
            version=next_version,
        )
        return added_chunks, previous_chunks, next_version

    def delete_document(self, source: str) -> int:
        deleted_chunks, _ = self._delete_existing_for_update(source)
        return deleted_chunks

    def list_documents(self, *, limit: int = 100, offset: int = 0) -> tuple[list[KnowledgeDocumentSummary], int]:
        result = self.collection.get(include=["metadatas"])
        metadatas = result.get("metadatas") or []
        documents_by_source: dict[str, dict[str, Any]] = {}

        for metadata in metadatas:
            metadata = metadata or {}
            source = str(metadata.get("source", "unknown")).strip() or "unknown"
            current = documents_by_source.setdefault(
                source,
                {
                    "source": source,
                    "document_type": "manual",
                    "module": "general",
                    "tags": set(),
                    "version": 1,
                    "chunk_count": 0,
                    "content_hash": None,
                    "updated_at": None,
                },
            )
            version = _optional_int(metadata.get("version")) or 1
            updated_at = _optional_str(metadata.get("updated_at"))
            current["chunk_count"] += 1
            current["version"] = max(int(current["version"]), version)
            current["document_type"] = _optional_str(metadata.get("document_type")) or current["document_type"]
            current["module"] = _optional_str(metadata.get("module")) or current["module"]
            current["content_hash"] = _optional_str(metadata.get("content_hash")) or current["content_hash"]
            if updated_at and (current["updated_at"] is None or updated_at > current["updated_at"]):
                current["updated_at"] = updated_at
            for tag in _split_tags(metadata.get("tags")):
                current["tags"].add(tag)

        summaries = [
            KnowledgeDocumentSummary(
                source=item["source"],
                document_type=item["document_type"],
                module=item["module"],
                tags=sorted(item["tags"]),
                version=item["version"],
                chunk_count=item["chunk_count"],
                content_hash=item["content_hash"],
                updated_at=item["updated_at"],
            )
            for item in documents_by_source.values()
        ]
        summaries.sort(key=lambda item: (item.updated_at or "", item.source), reverse=True)
        total = len(summaries)
        return summaries[offset : offset + limit], total

    def search(self, query: str, top_k: int = 5) -> list[KnowledgeChunk]:
        if top_k <= 0 or self.collection.count() == 0:
            return []

        result = self.collection.query(query_texts=[query], n_results=top_k)
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        chunks: list[KnowledgeChunk] = []
        for index, content in enumerate(documents):
            metadata = metadatas[index] or {}
            distance = distances[index] if index < len(distances) else None
            score = None if distance is None else max(0.0, 1.0 - float(distance))
            chunks.append(
                KnowledgeChunk(
                    content=content,
                    source=str(metadata.get("source", "unknown")),
                    score=score,
                    document_type=_optional_str(metadata.get("document_type")),
                    module=_optional_str(metadata.get("module")),
                    chunk=_optional_int(metadata.get("chunk")),
                    tags=_split_tags(metadata.get("tags")),
                )
            )
        return chunks

    def _add_document_chunks(
        self,
        document: KnowledgeDocument,
        *,
        chunk_size: int,
        version: int,
    ) -> int:
        chunks = _chunk_text(document.content, chunk_size)
        if not chunks:
            return 0
        self.collection.add(
            ids=[f"{uuid.uuid4()}" for _ in chunks],
            documents=chunks,
            metadatas=[
                _document_metadata(document, index=index, version=version)
                for index, _ in enumerate(chunks, start=1)
            ],
        )
        return len(chunks)

    def _delete_existing_for_update(self, source: str) -> tuple[int, int]:
        result = self.collection.get(where={"source": source}, include=["metadatas"])
        ids = result.get("ids") or []
        metadatas = result.get("metadatas") or []
        versions = [
            _optional_int(metadata.get("version")) or 1
            for metadata in metadatas
            if metadata
        ]
        next_version = (max(versions) + 1) if versions else 1
        if ids:
            self.collection.delete(ids=ids)
        return len(ids), next_version

    def _next_document_version(self, source: str) -> int:
        result = self.collection.get(where={"source": source}, include=["metadatas"])
        versions = [
            _optional_int(metadata.get("version")) or 1
            for metadata in (result.get("metadatas") or [])
            if metadata
        ]
        return (max(versions) + 1) if versions else 1


def _chunk_text(text: str, chunk_size: int) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(cleaned) <= chunk_size:
        return [cleaned] if cleaned else []

    chunks: list[str] = []
    start = 0
    overlap = min(120, max(20, chunk_size // 8))
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(cleaned):
            break
        start = max(0, end - overlap)
    return chunks


def _document_metadata(
    document: KnowledgeDocument,
    *,
    index: int,
    version: int,
) -> dict[str, Any]:
    return {
        "source": document.source,
        "document_type": document.document_type,
        "module": document.module,
        "chunk": index,
        "tags": ",".join(document.tags),
        "version": version,
        "content_hash": _content_hash(document.content),
        "updated_at": _utc_now(),
    }


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_project_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_embedding_function(settings: Settings) -> Any:
    provider = settings.embedding_provider.strip().lower().replace("-", "_")
    if provider == "hash":
        return HashEmbeddingFunction()
    if provider in {"sentence_transformers", "sentence_transformer"}:
        return SentenceTransformerEmbeddingFunction(
            model_name=settings.embedding_model,
            cache_dir=settings.embedding_cache_dir,
            device=settings.embedding_device,
            local_files_only=settings.embedding_local_files_only,
        )
    raise ChromaUnavailableError(
        f"Unsupported EMBEDDING_PROVIDER `{settings.embedding_provider}`. "
        "Use `hash` or `sentence_transformers`."
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _split_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]
