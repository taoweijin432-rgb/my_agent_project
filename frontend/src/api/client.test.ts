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
import type { CoverageEvaluationResponse, GenerateRequest } from "./types";

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
});
