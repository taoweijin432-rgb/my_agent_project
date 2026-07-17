import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiClient,
  ApiError,
  buildApiUrl,
  buildHealthUrl,
  buildQueryString,
  getErrorMessage,
  normalizeBaseUrl,
  normalizeErrorDetail
} from "./client";
import type {
  CoverageEvaluationResponse,
  GenerateRequest,
  TestExecutionReport,
  TestPlan,
  TestPlanGenerationRequest
} from "./types";

const REQUEST: GenerateRequest = {
  description: "生成登录接口测试用例",
  max_cases: 3,
  knowledge_top_k: 2,
  include_context: false,
  focus_types: ["functional"]
};

const COVERAGE: CoverageEvaluationResponse = {
  total_requirements: 1,
  covered_requirements: 0,
  coverage_rate: 0,
  total_keywords: 2,
  matched_keywords: 1,
  keyword_coverage_rate: 0.5,
  uncovered_requirement_ids: ["REQ-001"],
  items: [
    {
      requirement: {
        id: "REQ-001",
        title: "验证码过期",
        description: "",
        keywords: ["过期", "提示"],
        priority: "high",
        source: null
      },
      covered: false,
      coverage_score: 0.5,
      matched_case_ids: [],
      matched_case_titles: [],
      matched_keywords: ["过期"],
      missing_keywords: ["提示"]
    }
  ],
  warnings: ["uncovered_requirements"],
  recommendations: ["补充未覆盖验收点对应的测试用例：REQ-001。"]
};

const TEST_PLAN: TestPlan = {
  id: "plan-login",
  title: "登录测试计划",
  source: "client-test",
  requirements: [
    {
      id: "REQ-001",
      title: "登录成功",
      description: "登录成功",
      keywords: ["登录成功"],
      priority: "high",
      source: "client-test"
    }
  ],
  scope: {
    in_scope: ["登录 API"],
    out_of_scope: [],
    assumptions: [],
    risks: ["验证码过期"]
  },
  steps: [
    {
      id: "TP-001",
      title: "登录成功",
      objective: "调用登录接口",
      requirement_ids: ["REQ-001"],
      test_types: ["functional"],
      priority: "high",
      tool: "http",
      tool_args: { path: "/login" },
      success_criteria: ["返回 200"]
    }
  ]
};

const TEST_PLAN_REQUEST: TestPlanGenerationRequest = {
  description: "登录测试计划",
  source: "client-test",
  requirements: TEST_PLAN.requirements,
  context: [],
  max_steps: 8,
  use_llm: false,
  allow_llm_fallback: true
};

const TEST_REPORT: TestExecutionReport = {
  id: "report-plan-login",
  plan_id: "plan-login",
  status: "passed",
  summary: "登录测试计划: executed 1/1 step(s); passed=1.",
  tool_runs: [],
  requirement_coverage: { "REQ-001": true },
  defects: [],
  recommendations: []
};

describe("api client helpers", () => {
  it("normalizes base urls", () => {
    expect(normalizeBaseUrl(undefined)).toBe("/api/v1");
    expect(normalizeBaseUrl(" /api/v1/ ")).toBe("/api/v1");
    expect(normalizeBaseUrl("https://api.example.com/api/v1///")).toBe(
      "https://api.example.com/api/v1"
    );
  });

  it("builds api urls without duplicate slashes", () => {
    expect(buildApiUrl("/api/v1", "test-cases/generate")).toBe(
      "/api/v1/test-cases/generate"
    );
    expect(buildApiUrl("/api/v1", "/test-cases/generate")).toBe(
      "/api/v1/test-cases/generate"
    );
    expect(buildApiUrl("/", "/health")).toBe("/health");
  });

  it("derives health urls from api roots", () => {
    expect(buildHealthUrl("/api/v1")).toBe("/health");
    expect(buildHealthUrl("https://api.example.com/api/v1/")).toBe(
      "https://api.example.com/health"
    );
    expect(buildHealthUrl("/backend/api/v1")).toBe("/backend/health");
  });

  it("builds query strings and skips empty values", () => {
    expect(buildQueryString({ limit: 20, offset: 0, status: "" })).toBe(
      "?limit=20&offset=0"
    );
    expect(buildQueryString({ source: "知识 文档", missing: undefined })).toBe(
      "?source=%E7%9F%A5%E8%AF%86+%E6%96%87%E6%A1%A3"
    );
  });

  it("normalizes nested error payloads", () => {
    expect(normalizeErrorDetail({ detail: "Invalid API key." })).toBe(
      "Invalid API key."
    );
    expect(normalizeErrorDetail([{ detail: "field required" }, "bad request"])).toBe(
      "field required; bad request"
    );
    expect(getErrorMessage(new ApiError(401, { detail: "Invalid API key." }))).toBe(
      "401: Invalid API key."
    );
  });
});

describe("ApiClient requests", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends JSON requests with API key header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ cases: [], metadata: {}, retrieved_context: [] }), {
        status: 200,
        headers: { "content-type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({ baseUrl: "/api/v1/", apiKey: "test-key" });
    await client.generateTestCases(REQUEST);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/test-cases/generate");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({
      "Content-Type": "application/json",
      "X-API-Key": "test-key"
    });
    expect(JSON.parse(String(init.body))).toEqual(REQUEST);
  });

  it("uses the root health endpoint outside /api/v1", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", service: "AI Test Case Generator" }), {
        status: 200,
        headers: { "content-type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({
      baseUrl: "https://api.example.com/api/v1",
      apiKey: ""
    });
    await client.health();

    expect(fetchMock).toHaveBeenCalledWith("https://api.example.com/health");
  });

  it("throws ApiError with normalized JSON details", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "quality_gate_failed" } }), {
        status: 409,
        headers: { "content-type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({ baseUrl: "/api/v1", apiKey: "" });

    await expect(client.generateTestCases(REQUEST)).rejects.toMatchObject({
      status: 409,
      message: '{"code":"quality_gate_failed"}'
    });
  });

  it("returns blobs for export endpoints", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("xlsx", { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({ baseUrl: "/api/v1", apiKey: "test-key" });
    const blob = await client.exportExcel([], "cases.xlsx");

    expect(await blob.text()).toBe("xlsx");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/test-cases/export");
    expect(init.method).toBe("POST");
  });

  it("exports test plan execution reports as blobs", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("markdown", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({ baseUrl: "/api/v1", apiKey: "test-key" });
    const blob = await client.exportTestPlanReport(TEST_REPORT, {
      format: "markdown",
      filename: "report-plan-login.md"
    });

    expect(await blob.text()).toBe("markdown");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/test-plans/reports/export");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      report: TEST_REPORT,
      format: "markdown",
      filename: "report-plan-login.md"
    });
  });

  it("sends pytest adapter options for pytest exports", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("pytest", { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({ baseUrl: "/api/v1", apiKey: "test-key" });
    await client.exportPytest([], {
      filename: "login_cases.py",
      target_base_url_env: "LOGIN_BASE_URL",
      skip_by_default: false,
      adapter: "login_api"
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/test-cases/export/pytest");
    expect(JSON.parse(String(init.body))).toEqual({
      cases: [],
      filename: "login_cases.py",
      target_base_url_env: "LOGIN_BASE_URL",
      skip_by_default: false,
      adapter: "login_api"
    });
  });

  it("sends coverage gaps to the knowledge persistence endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          source: "knowledge/evaluation/login-gaps.md",
          version: 2,
          added_chunks: 1,
          replaced_chunks: 0,
          gap_count: 1,
          document_type: "evaluation",
          module: "login",
          tags: ["coverage-gap", "login"]
        }),
        { status: 200, headers: { "content-type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({ baseUrl: "/api/v1", apiKey: "test-key" });
    await client.upsertCoverageGaps(COVERAGE, {
      source: "knowledge/evaluation/login-gaps.md",
      module: "login",
      chunk_size: 500
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/evaluation/coverage/gaps/knowledge");
    expect(JSON.parse(String(init.body))).toEqual({
      coverage: COVERAGE,
      source: "knowledge/evaluation/login-gaps.md",
      document_type: "evaluation",
      module: "login",
      tags: ["coverage-gap", "login"],
      include_covered: false,
      chunk_size: 500
    });
  });

  it("sends test plan generation and execution requests", async () => {
    const report = {
      id: "report-plan-login",
      plan_id: "plan-login",
      status: "passed",
      summary: "passed",
      tool_runs: [],
      requirement_coverage: { "REQ-001": true },
      defects: [],
      recommendations: []
    };
    const job = {
      id: "job-1",
      status: "queued",
      created_at: "2026-07-12T00:00:00",
      updated_at: "2026-07-12T00:00:00",
      started_at: null,
      finished_at: null,
      error: null,
      request: {
        plan: TEST_PLAN,
        http_base_url: "http://testserver"
      },
      report: null
    };
    const workflowJob = {
      id: "workflow-job-1",
      status: "queued",
      created_at: "2026-07-12T00:00:00",
      updated_at: "2026-07-12T00:00:00",
      started_at: null,
      finished_at: null,
      error: null,
      request: {
        generation_request: TEST_PLAN_REQUEST,
        http_base_url: "http://testserver"
      },
      result: null
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(TEST_PLAN))
      .mockResolvedValueOnce(jsonResponse(report))
      .mockResolvedValueOnce(jsonResponse(job, 202))
      .mockResolvedValueOnce(jsonResponse({ jobs: [job], limit: 50, offset: 0 }))
      .mockResolvedValueOnce(jsonResponse(job))
      .mockResolvedValueOnce(jsonResponse(workflowJob, 202))
      .mockResolvedValueOnce(
        jsonResponse({ jobs: [workflowJob], limit: 20, offset: 0 })
      )
      .mockResolvedValueOnce(jsonResponse(workflowJob));
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient({ baseUrl: "/api/v1", apiKey: "test-key" });
    await client.generateTestPlan(TEST_PLAN_REQUEST);
    await client.executeTestPlan({
      plan: TEST_PLAN,
      http_base_url: "http://testserver"
    });
    await client.submitTestPlanExecutionJob({
      plan: TEST_PLAN,
      http_base_url: "http://testserver"
    });
    await client.listTestPlanExecutionJobs({ limit: 50, offset: 0, status: "queued" });
    await client.getTestPlanExecutionJob("job-1");
    await client.submitTestAgentWorkflowJob({
      generation_request: TEST_PLAN_REQUEST,
      http_base_url: "http://testserver"
    });
    await client.listTestAgentWorkflowJobs({ limit: 20, offset: 0, status: "queued" });
    await client.getTestAgentWorkflowJob("workflow-job-1");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/test-plans/generate");
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual(TEST_PLAN_REQUEST);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/test-plans/execute");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/test-plans/execution-jobs");
    expect(fetchMock.mock.calls[3][0]).toBe(
      "/api/v1/test-plans/execution-jobs?limit=50&offset=0&status=queued"
    );
    expect(fetchMock.mock.calls[4][0]).toBe("/api/v1/test-plans/execution-jobs/job-1");
    expect(fetchMock.mock.calls[5][0]).toBe("/api/v1/test-agent/workflow-jobs");
    expect(JSON.parse(String(fetchMock.mock.calls[5][1].body))).toEqual({
      generation_request: TEST_PLAN_REQUEST,
      http_base_url: "http://testserver"
    });
    expect(fetchMock.mock.calls[6][0]).toBe(
      "/api/v1/test-agent/workflow-jobs?limit=20&offset=0&status=queued"
    );
    expect(fetchMock.mock.calls[7][0]).toBe(
      "/api/v1/test-agent/workflow-jobs/workflow-job-1"
    );
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" }
  });
}
