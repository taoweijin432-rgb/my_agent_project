from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


__test__ = False


class TestCaseType(str, Enum):
    functional = "functional"
    boundary = "boundary"
    exception = "exception"
    permission = "permission"
    compatibility = "compatibility"
    performance = "performance"
    security = "security"


_TYPE_ALIASES = {
    "normal": TestCaseType.functional,
    "happy_path": TestCaseType.functional,
    "positive": TestCaseType.functional,
    "正常": TestCaseType.functional,
    "正常流程": TestCaseType.functional,
    "功能": TestCaseType.functional,
    "边界": TestCaseType.boundary,
    "边界值": TestCaseType.boundary,
    "异常": TestCaseType.exception,
    "异常流": TestCaseType.exception,
    "权限": TestCaseType.permission,
    "权限校验": TestCaseType.permission,
    "兼容": TestCaseType.compatibility,
    "兼容性": TestCaseType.compatibility,
    "性能": TestCaseType.performance,
    "安全": TestCaseType.security,
}


def _to_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        lines = [line.strip(" -\t") for line in value.splitlines()]
        values = [line for line in lines if line]
        return values or [value.strip()]
    return [str(value).strip()]


class TestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="")
    title: str = Field(..., min_length=1)
    precondition: str = Field(default="")
    steps: list[str] = Field(..., min_length=1)
    expected: list[str] = Field(..., min_length=1)
    type: TestCaseType

    @field_validator("id", "title", "precondition", mode="before")
    @classmethod
    def coerce_string(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "\n".join(str(item).strip() for item in value if str(item).strip())
        return str(value).strip()

    @field_validator("steps", "expected", mode="before")
    @classmethod
    def coerce_list(cls, value: Any) -> list[str]:
        return _to_list(value)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: Any) -> Any:
        if isinstance(value, TestCaseType):
            return value
        key = str(value).strip().lower()
        return _TYPE_ALIASES.get(key, value)


class TestCaseCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[TestCase] = Field(..., min_length=1)

    @model_validator(mode="after")
    def ensure_case_ids(self) -> "TestCaseCollection":
        for index, case in enumerate(self.cases, start=1):
            if not case.id:
                case.id = f"TC-{index:03d}"
        return self


class KnowledgeChunk(BaseModel):
    content: str
    source: str = "manual"
    score: float | None = None
    document_type: str | None = None
    module: str | None = None
    chunk: int | None = None
    tags: list[str] = Field(default_factory=list)


class GenerationMetadata(BaseModel):
    model: str
    attempts: int
    retrieved_chunks: int
    retrieved_sources: list[str] = Field(default_factory=list)
    prompt_version: str = "test-case-generation-v1"


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=5)
    max_cases: int = Field(default=12, ge=1, le=50)
    knowledge_top_k: int = Field(default=5, ge=0, le=10)
    include_context: bool = False
    focus_types: list[TestCaseType] | None = None


class GenerateResponse(BaseModel):
    cases: list[TestCase]
    metadata: GenerationMetadata
    retrieved_context: list[KnowledgeChunk] = Field(default_factory=list)


class GenerationRecordSummary(BaseModel):
    id: str
    created_at: str
    request_id: str | None = None
    status: Literal["success", "failed"]
    description: str
    duration_ms: float
    model: str | None = None
    attempts: int | None = None
    retrieved_chunks: int | None = None
    retrieved_sources: list[str] = Field(default_factory=list)
    case_count: int
    error: str | None = None


class GenerationRecordDetail(GenerationRecordSummary):
    request: GenerateRequest
    response: GenerateResponse | None = None


class GenerationRecordListResponse(BaseModel):
    records: list[GenerationRecordSummary]
    limit: int
    offset: int


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[TestCase] = Field(..., min_length=1)
    filename: str | None = Field(default=None)

    @field_validator("filename", mode="before")
    @classmethod
    def normalize_filename(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("filename must be a string")

        filename = value.strip()
        if not filename:
            return None

        invalid_chars = set('/\\:*?"<>|;\r\n')
        if any(char in invalid_chars for char in filename):
            raise ValueError("filename contains invalid characters")
        if filename in {".", ".."}:
            raise ValueError("filename is not allowed")

        if not filename.lower().endswith(".xlsx"):
            filename = f"{filename}.xlsx"
        if len(filename) > 128:
            raise ValueError("filename must be 128 characters or fewer")
        return filename


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    document_type: str = Field(default="manual")
    module: str = Field(default="general")
    tags: list[str] = Field(default_factory=list)


class KnowledgeDocumentSummary(BaseModel):
    source: str
    document_type: str = "manual"
    module: str = "general"
    tags: list[str] = Field(default_factory=list)
    version: int = 1
    chunk_count: int
    content_hash: str | None = None
    updated_at: str | None = None


class KnowledgeDocumentListResponse(BaseModel):
    documents: list[KnowledgeDocumentSummary]
    total: int
    limit: int
    offset: int


class KnowledgeDocumentUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: KnowledgeDocument
    chunk_size: int = Field(default=900, ge=200, le=3000)


class KnowledgeDocumentUpsertResponse(BaseModel):
    source: str
    version: int
    added_chunks: int
    replaced_chunks: int


class KnowledgeDocumentDeleteResponse(BaseModel):
    source: str
    deleted_chunks: int


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[KnowledgeDocument] = Field(..., min_length=1)
    chunk_size: int = Field(default=900, ge=200, le=3000)


class IngestResponse(BaseModel):
    added_chunks: int


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)


class QueryResponse(BaseModel):
    chunks: list[KnowledgeChunk]
