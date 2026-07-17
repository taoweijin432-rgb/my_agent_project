import type {
  CoverageGapKnowledgeUpsertResponse,
  CoverageEvaluationResponse,
  GateStatus,
  GenerateRequest,
  GenerateResponse,
  GenerationJobDetail,
  GenerationJobListResponse,
  GenerationRecordDetail,
  GenerationRecordListResponse,
  JobStatus,
  KnowledgeDocument,
  KnowledgeDocumentDeleteResponse,
  KnowledgeDocumentListResponse,
  KnowledgeDocumentUpsertResponse,
  QueryResponse,
  RecordStatus,
  RequirementPoint,
  TestAgentWorkflowJobDetail,
  TestAgentWorkflowJobListResponse,
  TestAgentWorkflowRequest,
  TestCase,
  TestExecutionReport,
  TestPlan,
  TestPlanExecutionJobDetail,
  TestPlanExecutionJobListResponse,
  TestPlanExecutionRequest,
  TestPlanGenerationRequest,
  TestReportExportFormat
} from "./types";

export interface ApiConfig {
  baseUrl: string;
  apiKey: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(normalizeErrorDetail(detail));
    this.status = status;
    this.detail = detail;
  }
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;

  constructor(config: ApiConfig) {
    this.baseUrl = normalizeBaseUrl(config.baseUrl);
    this.apiKey = config.apiKey;
  }

  async health(): Promise<{ status: string; service: string }> {
    const response = await fetch(buildHealthUrl(this.baseUrl));
    if (!response.ok) {
      throw new ApiError(response.status, await readResponseDetail(response));
    }
    return response.json();
  }

  generateTestCases(request: GenerateRequest): Promise<GenerateResponse> {
    return this.request("/test-cases/generate", {
      method: "POST",
      body: request
    });
  }

  submitGenerationJob(request: GenerateRequest): Promise<GenerationJobDetail> {
    return this.request("/test-cases/generation-jobs", {
      method: "POST",
      body: request
    });
  }

  listGenerationJobs(params: {
    limit?: number;
    offset?: number;
    status?: JobStatus | "";
  }): Promise<GenerationJobListResponse> {
    return this.request(`/test-cases/generation-jobs${buildQueryString(params)}`);
  }

  getGenerationJob(jobId: string): Promise<GenerationJobDetail> {
    return this.request(`/test-cases/generation-jobs/${encodeURIComponent(jobId)}`);
  }

  exportExcel(cases: TestCase[], filename?: string): Promise<Blob> {
    return this.requestBlob("/test-cases/export", {
      method: "POST",
      body: { cases, filename: filename || undefined }
    });
  }

  exportPytest(
    cases: TestCase[],
    options: {
      filename?: string;
      target_base_url_env?: string;
      skip_by_default?: boolean;
      adapter?: "template" | "login_api";
    } = {}
  ): Promise<Blob> {
    return this.requestBlob("/test-cases/export/pytest", {
      method: "POST",
      body: {
        cases,
        filename: options.filename || undefined,
        target_base_url_env: options.target_base_url_env || "TARGET_BASE_URL",
        skip_by_default: options.skip_by_default ?? true,
        adapter: options.adapter || "template"
      }
    });
  }

  evaluateCoverage(
    requirements: RequirementPoint[],
    cases: TestCase[],
    minKeywordMatchRatio: number
  ): Promise<CoverageEvaluationResponse> {
    return this.request("/evaluation/coverage", {
      method: "POST",
      body: {
        requirements,
        cases,
        min_keyword_match_ratio: minKeywordMatchRatio
      }
    });
  }

  upsertCoverageGaps(
    coverage: CoverageEvaluationResponse,
    options: {
      source?: string;
      document_type?: string;
      module?: string;
      tags?: string[];
      include_covered?: boolean;
      chunk_size?: number;
    } = {}
  ): Promise<CoverageGapKnowledgeUpsertResponse> {
    const moduleName = options.module || "coverage";
    return this.request("/evaluation/coverage/gaps/knowledge", {
      method: "POST",
      body: {
        coverage,
        source: options.source || "knowledge/evaluation/coverage-gaps.md",
        document_type: options.document_type || "evaluation",
        module: moduleName,
        tags: options.tags || ["coverage-gap", moduleName],
        include_covered: options.include_covered ?? false,
        chunk_size: options.chunk_size ?? 900
      }
    });
  }

  generateTestPlan(request: TestPlanGenerationRequest): Promise<TestPlan> {
    return this.request("/test-plans/generate", {
      method: "POST",
      body: request
    });
  }

  executeTestPlan(request: TestPlanExecutionRequest): Promise<TestExecutionReport> {
    return this.request("/test-plans/execute", {
      method: "POST",
      body: request
    });
  }

  exportTestPlanReport(
    report: TestExecutionReport,
    options: {
      format?: TestReportExportFormat;
      filename?: string;
    } = {}
  ): Promise<Blob> {
    return this.requestBlob("/test-plans/reports/export", {
      method: "POST",
      body: {
        report,
        format: options.format || "markdown",
        filename: options.filename || undefined
      }
    });
  }

  submitTestPlanExecutionJob(
    request: TestPlanExecutionRequest
  ): Promise<TestPlanExecutionJobDetail> {
    return this.request("/test-plans/execution-jobs", {
      method: "POST",
      body: request
    });
  }

  listTestPlanExecutionJobs(params: {
    limit?: number;
    offset?: number;
    status?: JobStatus | "";
  }): Promise<TestPlanExecutionJobListResponse> {
    return this.request(`/test-plans/execution-jobs${buildQueryString(params)}`);
  }

  getTestPlanExecutionJob(jobId: string): Promise<TestPlanExecutionJobDetail> {
    return this.request(`/test-plans/execution-jobs/${encodeURIComponent(jobId)}`);
  }

  submitTestAgentWorkflowJob(
    request: TestAgentWorkflowRequest
  ): Promise<TestAgentWorkflowJobDetail> {
    return this.request("/test-agent/workflow-jobs", {
      method: "POST",
      body: request
    });
  }

  listTestAgentWorkflowJobs(params: {
    limit?: number;
    offset?: number;
    status?: JobStatus | "";
  }): Promise<TestAgentWorkflowJobListResponse> {
    return this.request(`/test-agent/workflow-jobs${buildQueryString(params)}`);
  }

  getTestAgentWorkflowJob(jobId: string): Promise<TestAgentWorkflowJobDetail> {
    return this.request(`/test-agent/workflow-jobs/${encodeURIComponent(jobId)}`);
  }

  listKnowledgeDocuments(params: {
    limit?: number;
    offset?: number;
  }): Promise<KnowledgeDocumentListResponse> {
    return this.request(`/knowledge/documents${buildQueryString(params)}`);
  }

  upsertKnowledgeDocument(
    document: KnowledgeDocument,
    chunkSize: number
  ): Promise<KnowledgeDocumentUpsertResponse> {
    return this.request("/knowledge/documents/upsert", {
      method: "POST",
      body: { document, chunk_size: chunkSize }
    });
  }

  deleteKnowledgeDocument(source: string): Promise<KnowledgeDocumentDeleteResponse> {
    return this.request(`/knowledge/documents?source=${encodeURIComponent(source)}`, {
      method: "DELETE"
    });
  }

  queryKnowledge(query: string, topK: number): Promise<QueryResponse> {
    return this.request("/knowledge/query", {
      method: "POST",
      body: { query, top_k: topK }
    });
  }

  listGenerationRecords(params: {
    limit?: number;
    offset?: number;
    status?: RecordStatus | "";
  }): Promise<GenerationRecordListResponse> {
    return this.request(`/generation-records${buildQueryString(params)}`);
  }

  getGenerationRecord(recordId: string): Promise<GenerationRecordDetail> {
    return this.request(`/generation-records/${encodeURIComponent(recordId)}`);
  }

  listGenerationGates(params: {
    limit?: number;
    offset?: number;
    status?: GateStatus | "all";
  }): Promise<GenerationRecordListResponse> {
    return this.request(`/generation-gates${buildQueryString(params)}`);
  }

  resolveGenerationGate(
    recordId: string,
    decision: "approved" | "rejected",
    resolvedBy?: string,
    comment?: string
  ): Promise<GenerationRecordDetail> {
    return this.request(`/generation-gates/${encodeURIComponent(recordId)}/resolve`, {
      method: "POST",
      body: {
        decision,
        resolved_by: resolvedBy || undefined,
        comment: comment || undefined
      }
    });
  }

  private async request<T>(
    path: string,
    options: { method?: string; body?: unknown } = {}
  ): Promise<T> {
    const response = await fetch(buildApiUrl(this.baseUrl, path), {
      method: options.method || "GET",
      headers: this.headers(Boolean(options.body)),
      body: options.body ? JSON.stringify(options.body) : undefined
    });

    if (!response.ok) {
      throw new ApiError(response.status, await readResponseDetail(response));
    }

    return response.json();
  }

  private async requestBlob(
    path: string,
    options: { method?: string; body?: unknown }
  ): Promise<Blob> {
    const response = await fetch(buildApiUrl(this.baseUrl, path), {
      method: options.method || "GET",
      headers: this.headers(Boolean(options.body)),
      body: options.body ? JSON.stringify(options.body) : undefined
    });

    if (!response.ok) {
      throw new ApiError(response.status, await readResponseDetail(response));
    }

    return response.blob();
  }

  private headers(hasBody: boolean): HeadersInit {
    const headers: Record<string, string> = {};
    if (hasBody) {
      headers["Content-Type"] = "application/json";
    }
    if (this.apiKey) {
      headers["X-API-Key"] = this.apiKey;
    }
    return headers;
  }
}

export function normalizeErrorDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (detail && typeof detail === "object" && "detail" in detail) {
    return normalizeErrorDetail((detail as { detail: unknown }).detail);
  }
  if (Array.isArray(detail)) {
    return detail.map(normalizeErrorDetail).join("; ");
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return "请求失败";
  }
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.status}: ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return normalizeErrorDetail(error);
}

export function normalizeBaseUrl(value: string | undefined): string {
  return trimSlash(value?.trim() || "/api/v1");
}

export function buildHealthUrl(baseUrl: string): string {
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl);
  const apiRoot = normalizedBaseUrl.endsWith("/api/v1")
    ? normalizedBaseUrl.slice(0, -"/api/v1".length) || "/"
    : normalizedBaseUrl;
  return buildApiUrl(normalizeBaseUrl(apiRoot), "/health");
}

export function buildApiUrl(baseUrl: string, path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (baseUrl === "/") {
    return normalizedPath;
  }
  return `${baseUrl}${normalizedPath}`;
}

export function buildQueryString(
  params: Record<string, string | number | undefined>
): string {
  const values = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      values.set(key, String(value));
    }
  });
  const query = values.toString();
  return query ? `?${query}` : "";
}

async function readResponseDetail(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function trimSlash(value: string): string {
  if (value === "/") {
    return value;
  }
  return value.replace(/\/+$/, "");
}
