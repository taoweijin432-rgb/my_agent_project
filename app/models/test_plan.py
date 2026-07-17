from enum import Enum
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.test_case import KnowledgeChunk, RequirementPoint, TestCaseType


__test__ = False


class TestPlanPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TestToolType(str, Enum):
    manual = "manual"
    http = "http"
    pytest = "pytest"
    playwright = "playwright"
    sql = "sql"
    custom = "custom"


class ToolRunStatus(str, Enum):
    queued = "queued"
    running = "running"
    passed = "passed"
    failed = "failed"
    skipped = "skipped"
    blocked = "blocked"


class TestReportStatus(str, Enum):
    passed = "passed"
    failed = "failed"
    blocked = "blocked"
    incomplete = "incomplete"


class TestPlanExecutionJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class TestAgentWorkflowJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class TestAgentWorkflowStage(str, Enum):
    plan_generation = "plan_generation"
    tool_execution = "tool_execution"
    report_build = "report_build"


HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
HTTPJSONAssertionOperator = Literal["equals", "exists"]
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}


class HTTPJSONAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=200)
    operator: HTTPJSONAssertionOperator = "equals"
    expected: Any = None

    @field_validator("path", mode="before")
    @classmethod
    def normalize_path(cls, value: Any) -> str:
        text = str(value or "").strip()
        if text.startswith("$."):
            text = text[2:]
        elif text.startswith("$"):
            text = text[1:].lstrip(".")
        if not text or ".." in text:
            raise ValueError("json assertion path must be a non-empty dot path")
        return text


class HTTPToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    method: HTTPMethod | None = None
    path: str | None = Field(default=None, max_length=300)
    endpoint_hint: str | None = Field(default=None, max_length=300)
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any = Field(default=None, alias="json")
    expected_status: int | list[int] = 200
    json_assertions: list[HTTPJSONAssertion] = Field(default_factory=list)

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: Any) -> str | None:
        if value is None:
            return None
        method = str(value).strip().upper()
        return method or None

    @field_validator("path", "endpoint_hint", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("headers", mode="before")
    @classmethod
    def normalize_headers(cls, value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("headers must be an object")
        return {str(key): str(item) for key, item in value.items()}

    @field_validator("expected_status")
    @classmethod
    def validate_expected_status(cls, value: int | list[int]) -> int | list[int]:
        statuses = value if isinstance(value, list) else [value]
        if not statuses:
            raise ValueError("expected_status must not be empty")
        invalid = [status for status in statuses if status < 100 or status > 599]
        if invalid:
            raise ValueError(f"Invalid expected HTTP status: {invalid[0]}")
        return value

    @model_validator(mode="after")
    def validate_resolved_target(self) -> "HTTPToolArgs":
        _ = self.resolved_path
        _ = self.resolved_method
        return self

    @property
    def expected_statuses(self) -> set[int]:
        statuses = (
            self.expected_status
            if isinstance(self.expected_status, list)
            else [self.expected_status]
        )
        return set(statuses)

    @property
    def resolved_method(self) -> str:
        method, _ = self._resolve_method_and_path()
        return method

    @property
    def resolved_path(self) -> str:
        _, path = self._resolve_method_and_path()
        return path

    def _resolve_method_and_path(self) -> tuple[str, str]:
        method: str | None = self.method
        path = self.path or self.endpoint_hint or ""
        if " " in path:
            possible_method, possible_path = path.split(None, 1)
            possible_method = possible_method.upper()
            if possible_method in _HTTP_METHODS:
                method = method or possible_method
                path = possible_path.strip()

        method = method or "GET"
        if method not in _HTTP_METHODS:
            raise ValueError(f"Unsupported HTTP method: {method}")
        if not path:
            raise ValueError("HTTP step requires path or endpoint_hint")
        if "://" in path or path.startswith("//"):
            raise ValueError("HTTP step path must be relative to base_url")
        if not path.startswith("/"):
            path = f"/{path}"
        return method, path


class PytestToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_path: str | None = Field(default=None, max_length=300)
    path: str | None = Field(default=None, max_length=300)
    keyword: str | None = Field(default=None, max_length=200)
    marker: str | None = Field(default=None, max_length=200)
    maxfail: int = Field(default=1, ge=1, le=100)

    @field_validator("test_path", "path", "keyword", "marker", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @model_validator(mode="after")
    def validate_resolved_test_path(self) -> "PytestToolArgs":
        _ = self.resolved_test_path
        return self

    @property
    def resolved_test_path(self) -> str:
        test_path = self.test_path or self.path
        if not test_path:
            raise ValueError("pytest step requires test_path")
        return test_path


class TestPlanScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class TestPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=200)
    objective: str = Field(..., min_length=1, max_length=1000)
    requirement_ids: list[str] = Field(default_factory=list)
    test_types: list[TestCaseType] = Field(default_factory=list)
    priority: TestPlanPriority = TestPlanPriority.medium
    tool: TestToolType = TestToolType.manual
    tool_args: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[str] = Field(default_factory=list)

    @field_validator("requirement_ids", "success_criteria", mode="before")
    @classmethod
    def normalize_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.splitlines() if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]


class TestPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=200)
    source: str | None = Field(default=None, max_length=240)
    requirements: list[RequirementPoint] = Field(default_factory=list)
    scope: TestPlanScope = Field(default_factory=TestPlanScope)
    steps: list[TestPlanStep] = Field(default_factory=list)


class TestPlanGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=5)
    source: str | None = Field(default=None, max_length=240)
    requirements: list[RequirementPoint] = Field(default_factory=list)
    context: list[KnowledgeChunk] = Field(default_factory=list)
    max_steps: int = Field(default=12, ge=1, le=50)
    use_llm: bool = False
    allow_llm_fallback: bool = True


class ToolRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=80)
    plan_step_id: str = Field(..., min_length=1, max_length=80)
    tool: TestToolType
    status: ToolRunStatus
    command: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    output_summary: str = ""
    artifact_paths: list[str] = Field(default_factory=list)


def summarize_report_status(tool_runs: list[ToolRun]) -> TestReportStatus:
    if not tool_runs:
        return TestReportStatus.incomplete

    statuses = {tool_run.status for tool_run in tool_runs}
    if statuses & {ToolRunStatus.queued, ToolRunStatus.running}:
        return TestReportStatus.incomplete
    if ToolRunStatus.failed in statuses:
        return TestReportStatus.failed
    if ToolRunStatus.blocked in statuses:
        return TestReportStatus.blocked
    if ToolRunStatus.passed in statuses:
        return TestReportStatus.passed

    return TestReportStatus.incomplete


class TestExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=80)
    plan_id: str = Field(..., min_length=1, max_length=80)
    status: TestReportStatus
    summary: str = ""
    tool_runs: list[ToolRun] = Field(default_factory=list)
    requirement_coverage: dict[str, bool] = Field(default_factory=dict)
    defects: list[str] = Field(default_factory=list)
    reason_classifications: dict[str, str] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)


class TestExecutionReportExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: TestExecutionReport
    format: Literal["markdown", "json"] = "markdown"
    filename: str | None = Field(default=None, max_length=240)

    @field_validator("format", mode="before")
    @classmethod
    def normalize_format(cls, value: Any) -> str:
        return str(value or "markdown").strip().lower()

    @field_validator("filename", mode="before")
    @classmethod
    def normalize_filename(cls, value: Any) -> str | None:
        if value is None:
            return None
        filename = str(value).strip()
        return filename or None


class TestPlanStepExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: TestPlanStep
    http_base_url: str = Field(..., min_length=1, max_length=300)

    @field_validator("http_base_url", mode="before")
    @classmethod
    def normalize_http_base_url(cls, value: Any) -> str:
        return _normalize_http_base_url_value(value)


class TestPlanExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: TestPlan
    http_base_url: str = Field(..., min_length=1, max_length=300)

    @field_validator("http_base_url", mode="before")
    @classmethod
    def normalize_http_base_url(cls, value: Any) -> str:
        return _normalize_http_base_url_value(value)


class TestAgentWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_request: TestPlanGenerationRequest
    http_base_url: str = Field(..., min_length=1, max_length=300)

    @field_validator("http_base_url", mode="before")
    @classmethod
    def normalize_http_base_url(cls, value: Any) -> str:
        return _normalize_http_base_url_value(value)


class TestAgentWorkflowStageTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: TestAgentWorkflowStage
    started_at: str
    finished_at: str
    duration_ms: float = Field(..., ge=0)
    status: Literal["succeeded", "failed"] = "succeeded"
    error_code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TestAgentWorkflowTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_ms: float | None = Field(default=None, ge=0)
    stages: list[TestAgentWorkflowStageTiming] = Field(default_factory=list)


class TestAgentWorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: TestPlan
    report: TestExecutionReport
    timing: TestAgentWorkflowTiming = Field(default_factory=TestAgentWorkflowTiming)


def _normalize_http_base_url_value(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("http_base_url must be a string")
    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("http_base_url must be an absolute HTTP/HTTPS URL")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError("http_base_url must not include params, query, or fragment")
    return base_url


class TestPlanExecutionJobError(BaseModel):
    code: str
    message: str


class TestPlanExecutionJobSummary(BaseModel):
    id: str
    status: TestPlanExecutionJobStatus
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: TestPlanExecutionJobError | None = None


class TestPlanExecutionJobDetail(TestPlanExecutionJobSummary):
    request: TestPlanExecutionRequest
    report: TestExecutionReport | None = None


class TestPlanExecutionJobListResponse(BaseModel):
    jobs: list[TestPlanExecutionJobSummary]
    limit: int
    offset: int


class TestAgentWorkflowJobError(BaseModel):
    code: str
    message: str
    stage: TestAgentWorkflowStage | None = None
    timing: TestAgentWorkflowTiming = Field(default_factory=TestAgentWorkflowTiming)


class TestAgentWorkflowJobTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_wait_ms: float | None = Field(default=None, ge=0)
    job_runtime_ms: float | None = Field(default=None, ge=0)
    job_total_ms: float | None = Field(default=None, ge=0)
    workflow_total_ms: float | None = Field(default=None, ge=0)
    plan_generation_ms: float | None = Field(default=None, ge=0)
    tool_execution_ms: float | None = Field(default=None, ge=0)
    report_build_ms: float | None = Field(default=None, ge=0)


class TestAgentWorkflowJobSummary(BaseModel):
    id: str
    status: TestAgentWorkflowJobStatus
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: TestAgentWorkflowJobError | None = None
    timing: TestAgentWorkflowJobTiming = Field(default_factory=TestAgentWorkflowJobTiming)


class TestAgentWorkflowJobDetail(TestAgentWorkflowJobSummary):
    request: TestAgentWorkflowRequest
    result: TestAgentWorkflowResult | None = None


class TestAgentWorkflowJobListResponse(BaseModel):
    jobs: list[TestAgentWorkflowJobSummary]
    limit: int
    offset: int
