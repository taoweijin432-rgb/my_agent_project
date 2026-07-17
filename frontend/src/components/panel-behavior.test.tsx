import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiClient } from "../api/client";
import { downloadBlob } from "../api/download";
import type {
  CoverageEvaluationResponse,
  GenerateRequest,
  GenerateResponse,
  GenerationGateDetail,
  GenerationRecordDetail,
  GenerationRecordSummary,
  GenerationUsage,
  TestCase,
  TestAgentWorkflowJobDetail,
  TestExecutionReport,
  TestPlan,
  TestPlanExecutionJobDetail
} from "../api/types";
import { CoveragePanel } from "./CoveragePanel";
import { GeneratePanel } from "./GeneratePanel";
import { HistoryPanel } from "./HistoryPanel";
import { JobsPanel } from "./JobsPanel";
import { KnowledgePanel } from "./KnowledgePanel";
import { ResultView } from "./ResultView";
import { TestPlanPanel } from "./TestPlanPanel";

vi.mock("../api/download", () => ({
  downloadBlob: vi.fn()
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

const request: GenerateRequest = {
  description: "登录需求",
  max_cases: 1,
  knowledge_top_k: 0,
  include_context: false,
  focus_types: null
};

const usage: GenerationUsage = {
  prompt_characters: 0,
  completion_characters: 0,
  total_characters: 0,
  prompt_tokens_estimate: 0,
  completion_tokens_estimate: 0,
  total_tokens_estimate: 0,
  estimated_cost: null,
  currency: null
};

const cases: TestCase[] = [
  {
    id: "TC-001",
    title: "登录成功",
    precondition: "用户已注册",
    steps: ["输入手机号", "输入验证码"],
    expected: ["登录成功"],
    type: "functional"
  }
];

const response: GenerateResponse = {
  cases,
  metadata: {
    model: "test-model",
    attempts: 1,
    retrieved_chunks: 0,
    retrieved_sources: [],
    prompt_version: "test",
    workflow_backend: "local",
    usage,
    review: null,
    workflow_steps: []
  },
  retrieved_context: []
};

const testPlan: TestPlan = {
  id: "plan-login",
  title: "登录测试计划",
  source: "panel-test",
  requirements: [
    {
      id: "REQ-001",
      title: "登录成功",
      description: "登录成功",
      keywords: ["登录成功"],
      priority: "high",
      source: "panel-test"
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

const executionReport: TestExecutionReport = {
  id: "report-plan-login",
  plan_id: "plan-login",
  status: "passed",
  summary: "登录测试计划: executed 1/1 step(s); passed=1.",
  tool_runs: [
    {
      id: "run-1",
      plan_step_id: "TP-001",
      tool: "http",
      status: "passed",
      command: ["GET", "/login"],
      started_at: null,
      finished_at: null,
      exit_code: 0,
      output_summary: "HTTP 200",
      artifact_paths: ["data/test-artifacts/run-1/output.txt"]
    }
  ],
  requirement_coverage: { "REQ-001": true },
  defects: [],
  recommendations: ["继续补充异常路径。"]
};

const executionJob: TestPlanExecutionJobDetail = {
  id: "execution-job-1",
  status: "queued",
  created_at: "2026-07-12T09:00:00",
  updated_at: "2026-07-12T09:00:00",
  started_at: null,
  finished_at: null,
  error: null,
  request: {
    plan: testPlan,
    http_base_url: "http://testserver"
  },
  report: null
};

const workflowJob: TestAgentWorkflowJobDetail = {
  id: "workflow-job-1",
  status: "queued",
  created_at: "2026-07-12T09:05:00",
  updated_at: "2026-07-12T09:05:00",
  started_at: null,
  finished_at: null,
  error: null,
  timing: {
    queue_wait_ms: null,
    job_runtime_ms: null,
    job_total_ms: null,
    workflow_total_ms: null,
    plan_generation_ms: null,
    tool_execution_ms: null,
    report_build_ms: null
  },
  request: {
    generation_request: {
      description: "登录测试计划",
      source: "panel-test",
      requirements: testPlan.requirements,
      context: [],
      max_steps: 8,
      use_llm: false,
      allow_llm_fallback: true
    },
    http_base_url: "http://testserver"
  },
  result: null
};

describe("panel behavior", () => {
  it("normalizes sync generation requests and submits async generation jobs", async () => {
    const job = {
      id: "job-2",
      status: "queued" as const,
      created_at: "2026-07-09T09:02:00",
      updated_at: "2026-07-09T09:02:00",
      started_at: null,
      finished_at: null,
      record_id: null,
      error: null,
      request,
      response: null
    };
    const api = {
      generateTestCases: vi.fn().mockResolvedValue(response),
      submitGenerationJob: vi.fn().mockResolvedValue(job)
    } as unknown as ApiClient;
    const onCasesReady = vi.fn();

    render(<GeneratePanel api={api} onCasesReady={onCasesReady} />);

    fireEvent.change(screen.getByLabelText("需求描述"), {
      target: { value: "  新登录需求  " }
    });
    fireEvent.click(screen.getByRole("button", { name: "同步生成" }));

    await waitFor(() =>
      expect(api.generateTestCases).toHaveBeenCalledWith(
        expect.objectContaining({ description: "新登录需求" })
      )
    );
    expect(onCasesReady).toHaveBeenCalledWith(cases);
    expect(await screen.findByText("TC-001")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "提交任务" }));
    await waitFor(() =>
      expect(api.submitGenerationJob).toHaveBeenCalledWith(
        expect.objectContaining({ description: "新登录需求" })
      )
    );
    expect(await screen.findByText("任务已提交：job-2")).toBeInTheDocument();
  });

  it("loads generation jobs and sends completed job cases back to the app", async () => {
    const jobSummary = {
      id: "job-1",
      status: "succeeded" as const,
      created_at: "2026-07-09T09:00:00",
      updated_at: "2026-07-09T09:00:01",
      started_at: null,
      finished_at: null,
      record_id: "record-1",
      error: null
    };
    const api = {
      listGenerationJobs: vi.fn().mockResolvedValue({
        jobs: [jobSummary],
        limit: 50,
        offset: 0
      }),
      getGenerationJob: vi.fn().mockResolvedValue({
        ...jobSummary,
        request,
        response
      })
    } as unknown as ApiClient;
    const onCasesReady = vi.fn();

    render(<JobsPanel api={api} onCasesReady={onCasesReady} />);

    expect(await screen.findByText("job-1")).toBeInTheDocument();
    fireEvent.click(screen.getByText("job-1").closest("tr") as HTMLTableRowElement);

    await waitFor(() => expect(api.getGenerationJob).toHaveBeenCalledWith("job-1"));
    expect(onCasesReady).toHaveBeenCalledWith(cases);
    expect(await screen.findByText("TC-001")).toBeInTheDocument();
  });

  it("generates, executes, and submits test plan execution jobs", async () => {
    const api = {
      listTestPlanExecutionJobs: vi.fn().mockResolvedValue({
        jobs: [],
        limit: 50,
        offset: 0
      }),
      listTestAgentWorkflowJobs: vi.fn().mockResolvedValue({
        jobs: [],
        limit: 50,
        offset: 0
      }),
      generateTestPlan: vi.fn().mockResolvedValue(testPlan),
      executeTestPlan: vi.fn().mockResolvedValue(executionReport),
      submitTestPlanExecutionJob: vi.fn().mockResolvedValue(executionJob),
      submitTestAgentWorkflowJob: vi.fn().mockResolvedValue(workflowJob),
      exportTestPlanReport: vi.fn().mockResolvedValue(new Blob(["report"]))
    } as unknown as ApiClient;

    render(<TestPlanPanel api={api} />);

    expect(await screen.findByText("暂无执行任务")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("需求描述"), {
      target: { value: "  登录测试计划  " }
    });
    fireEvent.click(screen.getByRole("button", { name: "生成计划" }));

    await waitFor(() =>
      expect(api.generateTestPlan).toHaveBeenCalledWith(
        expect.objectContaining({ description: "登录测试计划" })
      )
    );
    expect(await screen.findByText("TP-001")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "提交完整任务" }));
    await waitFor(() =>
      expect(api.submitTestAgentWorkflowJob).toHaveBeenCalledWith({
        generation_request: expect.objectContaining({ description: "登录测试计划" }),
        http_base_url: "http://testserver"
      })
    );
    expect(await screen.findByText("Workflow 任务已提交：workflow-job-1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "同步执行" }));
    await waitFor(() =>
      expect(api.executeTestPlan).toHaveBeenCalledWith({
        plan: testPlan,
        http_base_url: "http://testserver"
      })
    );
    expect(await screen.findByText("执行报告")).toBeInTheDocument();
    expect(screen.getByText("HTTP 200")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "导出 Markdown 报告" }));
    await waitFor(() =>
      expect(api.exportTestPlanReport).toHaveBeenCalledWith(executionReport, {
        format: "markdown",
        filename: "report-plan-login.md"
      })
    );
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "report-plan-login.md");

    fireEvent.click(screen.getByRole("button", { name: "JSON" }));
    await waitFor(() =>
      expect(api.exportTestPlanReport).toHaveBeenCalledWith(executionReport, {
        format: "json",
        filename: "report-plan-login.json"
      })
    );
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "report-plan-login.json");

    fireEvent.click(screen.getByRole("button", { name: "提交执行任务" }));
    await waitFor(() =>
      expect(api.submitTestPlanExecutionJob).toHaveBeenCalledWith({
        plan: testPlan,
        http_base_url: "http://testserver"
      })
    );
    expect(await screen.findByText("执行任务已提交：execution-job-1")).toBeInTheDocument();
  });

  it("loads test plan execution jobs and renders report details", async () => {
    const completedJob: TestPlanExecutionJobDetail = {
      ...executionJob,
      status: "succeeded",
      report: executionReport
    };
    const api = {
      listTestPlanExecutionJobs: vi.fn().mockResolvedValue({
        jobs: [completedJob],
        limit: 50,
        offset: 0
      }),
      listTestAgentWorkflowJobs: vi.fn().mockResolvedValue({
        jobs: [],
        limit: 50,
        offset: 0
      }),
      getTestPlanExecutionJob: vi.fn().mockResolvedValue(completedJob)
    } as unknown as ApiClient;

    render(<TestPlanPanel api={api} />);

    expect(await screen.findByText("execution-job-1")).toBeInTheDocument();
    fireEvent.click(screen.getByText("execution-job-1").closest("tr") as HTMLTableRowElement);

    await waitFor(() =>
      expect(api.getTestPlanExecutionJob).toHaveBeenCalledWith("execution-job-1")
    );
    expect(
      await screen.findAllByText("登录测试计划: executed 1/1 step(s); passed=1.")
    ).not.toHaveLength(0);
    expect(screen.getAllByText("继续补充异常路径。")).not.toHaveLength(0);
  });

  it("loads test agent workflow jobs and hydrates plan and report results", async () => {
    const completedWorkflowJob: TestAgentWorkflowJobDetail = {
      ...workflowJob,
      status: "succeeded",
      updated_at: "2026-07-12T09:06:00",
      started_at: "2026-07-12T09:05:01",
      finished_at: "2026-07-12T09:06:00",
      timing: {
        queue_wait_ms: 1000,
        job_runtime_ms: 59000,
        job_total_ms: 60000,
        workflow_total_ms: 58000,
        plan_generation_ms: 42000,
        tool_execution_ms: 1500,
        report_build_ms: 43
      },
      result: {
        plan: testPlan,
        report: executionReport,
        timing: {
          total_ms: 58000,
          stages: [
            {
              name: "plan_generation",
              started_at: "2026-07-12T09:05:01",
              finished_at: "2026-07-12T09:05:43",
              duration_ms: 42000,
              details: {
                used_llm: true,
                used_fallback: false,
                cache_status: "miss",
                llm: {
                  attempt_count: 1,
                  retry_count: 0,
                  total_duration_ms: 13948.734,
                  last_status: "succeeded"
                }
              }
            },
            {
              name: "tool_execution",
              started_at: "2026-07-12T09:05:43",
              finished_at: "2026-07-12T09:05:44.500",
              duration_ms: 1500
            },
            {
              name: "report_build",
              started_at: "2026-07-12T09:05:44.500",
              finished_at: "2026-07-12T09:05:44.543",
              duration_ms: 43
            }
          ]
        }
      }
    };
    const api = {
      listTestPlanExecutionJobs: vi.fn().mockResolvedValue({
        jobs: [],
        limit: 50,
        offset: 0
      }),
      listTestAgentWorkflowJobs: vi.fn().mockResolvedValue({
        jobs: [completedWorkflowJob],
        limit: 50,
        offset: 0
      }),
      getTestAgentWorkflowJob: vi.fn().mockResolvedValue(completedWorkflowJob)
    } as unknown as ApiClient;

    render(<TestPlanPanel api={api} />);

    expect(await screen.findByText("workflow-job-1")).toBeInTheDocument();
    fireEvent.click(screen.getByText("workflow-job-1").closest("tr") as HTMLTableRowElement);

    await waitFor(() =>
      expect(api.getTestAgentWorkflowJob).toHaveBeenCalledWith("workflow-job-1")
    );
    expect(await screen.findAllByText("TP-001")).not.toHaveLength(0);
    expect(screen.getByText("42.00s")).toBeInTheDocument();
    expect(screen.getByText("1.50s")).toBeInTheDocument();
    expect(screen.getByText("43ms")).toBeInTheDocument();
    expect(screen.getByText("LLM尝试")).toBeInTheDocument();
    expect(screen.getByText("LLM重试")).toBeInTheDocument();
    expect(screen.getByText("LLM总耗时")).toBeInTheDocument();
    expect(screen.getByText("13.95s")).toBeInTheDocument();
    expect(screen.getByText("miss")).toBeInTheDocument();
    expect(screen.getByText("succeeded")).toBeInTheDocument();
    expect(
      screen.getAllByText("登录测试计划: executed 1/1 step(s); passed=1.")
    ).not.toHaveLength(0);
    expect(screen.getAllByText("继续补充异常路径。")).not.toHaveLength(0);
  });

  it("resolves a pending generation gate from the history panel", async () => {
    const gate: GenerationGateDetail = {
      code: "quality_gate_failed",
      gate: "quality",
      message: "质量门控未通过",
      action_required: "请人工审批",
      usage: null,
      review: null
    };
    const summary: GenerationRecordSummary = {
      id: "record-1",
      created_at: "2026-07-09T09:00:00",
      request_id: "request-1",
      status: "failed",
      description: "登录质量门控",
      duration_ms: 120,
      model: null,
      attempts: null,
      retrieved_chunks: null,
      retrieved_sources: [],
      case_count: 0,
      error: "质量门控未通过",
      usage,
      gate,
      gate_resolution: {
        status: "pending",
        resolved_at: null,
        resolved_by: null,
        comment: null
      }
    };
    const detail: GenerationRecordDetail = {
      ...summary,
      request,
      response: null,
      quality: null
    };
    const resolvedDetail: GenerationRecordDetail = {
      ...detail,
      gate_resolution: {
        status: "approved",
        resolved_at: "2026-07-09T09:01:00",
        resolved_by: "qa-owner",
        comment: "允许继续"
      }
    };
    const api = {
      listGenerationRecords: vi.fn().mockResolvedValue({ records: [], limit: 50, offset: 0 }),
      listGenerationGates: vi.fn().mockResolvedValue({ records: [summary], limit: 50, offset: 0 }),
      getGenerationRecord: vi.fn().mockResolvedValue(detail),
      resolveGenerationGate: vi.fn().mockResolvedValue(resolvedDetail)
    } as unknown as ApiClient;

    render(<HistoryPanel api={api} onCasesReady={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "门控" }));
    fireEvent.click(await screen.findByText("登录质量门控"));

    fireEvent.change(await screen.findByLabelText("处理人"), {
      target: { value: "qa-owner" }
    });
    fireEvent.change(screen.getByLabelText("备注"), {
      target: { value: "允许继续" }
    });
    fireEvent.click(screen.getByRole("button", { name: "批准" }));

    await waitFor(() =>
      expect(api.resolveGenerationGate).toHaveBeenCalledWith(
        "record-1",
        "approved",
        "qa-owner",
        "允许继续"
      )
    );
    await waitFor(() => {
      const approvedBadges = screen
        .getAllByText("已批准")
        .filter((element) => element.classList.contains("status-badge"));
      expect(approvedBadges).toHaveLength(1);
    });
  });

  it("opens the coverage panel from a successful history record", async () => {
    const summary: GenerationRecordSummary = {
      id: "record-success",
      created_at: "2026-07-09T09:00:00",
      request_id: "request-success",
      status: "success",
      description: "登录成功记录",
      duration_ms: 180,
      model: "test-model",
      attempts: 1,
      retrieved_chunks: 0,
      retrieved_sources: [],
      case_count: 1,
      error: null,
      usage,
      gate: null,
      gate_resolution: null
    };
    const detail: GenerationRecordDetail = {
      ...summary,
      request,
      response,
      quality: null
    };
    const api = {
      listGenerationRecords: vi.fn().mockResolvedValue({ records: [summary], limit: 50, offset: 0 }),
      getGenerationRecord: vi.fn().mockResolvedValue(detail)
    } as unknown as ApiClient;
    const onCasesReady = vi.fn();
    const onOpenCoverage = vi.fn();

    render(
      <HistoryPanel
        api={api}
        onCasesReady={onCasesReady}
        onOpenCoverage={onOpenCoverage}
      />
    );

    fireEvent.click(await screen.findByText("登录成功记录"));

    await waitFor(() => expect(api.getGenerationRecord).toHaveBeenCalledWith("record-success"));
    expect(onCasesReady).toHaveBeenCalledWith(cases);

    fireEvent.click(await screen.findByRole("button", { name: "覆盖率" }));

    expect(onOpenCoverage).toHaveBeenCalledTimes(1);
    expect(onCasesReady).toHaveBeenLastCalledWith(cases);
  });

  it("saves, deletes, and queries knowledge documents", async () => {
    const api = {
      listKnowledgeDocuments: vi.fn().mockResolvedValue({
        documents: [
          {
            source: "knowledge/prd/login.md",
            document_type: "prd",
            module: "login",
            tags: ["login"],
            version: 1,
            chunk_count: 2,
            content_hash: null,
            updated_at: null
          }
        ],
        total: 1,
        limit: 100,
        offset: 0
      }),
      upsertKnowledgeDocument: vi.fn().mockResolvedValue({
        source: "manual/login-prd.md",
        version: 2,
        added_chunks: 1,
        replaced_chunks: 1
      }),
      deleteKnowledgeDocument: vi.fn().mockResolvedValue({
        source: "knowledge/prd/login.md",
        deleted_chunks: 2
      }),
      queryKnowledge: vi.fn().mockResolvedValue({
        chunks: [
          {
            content: "验证码 6 位数字，5 分钟有效。",
            source: "knowledge/prd/login.md",
            score: 0.91,
            document_type: "prd",
            module: "login",
            chunk: 0,
            tags: ["login"]
          }
        ]
      })
    } as unknown as ApiClient;
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<KnowledgePanel api={api} />);

    expect(await screen.findByText("knowledge/prd/login.md")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("内容"), {
      target: { value: "新的登录 PRD 内容" }
    });
    fireEvent.click(screen.getByRole("button", { name: "保存文档" }));
    await waitFor(() =>
      expect(api.upsertKnowledgeDocument).toHaveBeenCalledWith(
        expect.objectContaining({ content: "新的登录 PRD 内容" }),
        900
      )
    );
    expect(await screen.findByText(/manual\/login-prd\.md v2 已更新/)).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("删除文档"));
    await waitFor(() =>
      expect(api.deleteKnowledgeDocument).toHaveBeenCalledWith("knowledge/prd/login.md")
    );

    const queryForm = document.querySelector(".query-form") as HTMLFormElement;
    fireEvent.change(within(queryForm).getByRole("textbox"), {
      target: { value: "验证码规则" }
    });
    fireEvent.click(within(queryForm).getByRole("button", { name: "检索" }));

    await waitFor(() => expect(api.queryKnowledge).toHaveBeenCalledWith("验证码规则", 5));
    expect(await screen.findByText("验证码 6 位数字，5 分钟有效。")).toBeInTheDocument();
  });

  it("exports generated results with the requested base filename", async () => {
    const api = {
      exportExcel: vi.fn().mockResolvedValue(new Blob(["xlsx"])),
      exportPytest: vi.fn().mockResolvedValue(new Blob(["pytest"]))
    } as unknown as ApiClient;

    render(<ResultView api={api} response={response} />);

    fireEvent.change(screen.getByLabelText("导出文件名"), {
      target: { value: "login-cases" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Excel" }));

    await waitFor(() => expect(api.exportExcel).toHaveBeenCalledWith(cases, "login-cases.xlsx"));
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "login-cases.xlsx");

    fireEvent.click(screen.getByRole("button", { name: "pytest" }));

    await waitFor(() =>
      expect(api.exportPytest).toHaveBeenCalledWith(cases, {
        filename: "login-cases.py"
      })
    );
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "login-cases.py");
  });

  it("shows coverage errors before calling the API when there are no cases", async () => {
    const api = {
      evaluateCoverage: vi.fn()
    } as unknown as ApiClient;

    render(<CoveragePanel api={api} currentCases={[]} />);

    fireEvent.click(screen.getByRole("button", { name: "评估覆盖率" }));

    expect(await screen.findByText("当前会话没有可评估的测试用例。")).toBeInTheDocument();
    expect(api.evaluateCoverage).not.toHaveBeenCalled();
  });

  it("evaluates coverage and renders matched requirement results", async () => {
    const coverage: CoverageEvaluationResponse = {
      total_requirements: 1,
      covered_requirements: 1,
      coverage_rate: 1,
      total_keywords: 2,
      matched_keywords: 2,
      keyword_coverage_rate: 1,
      uncovered_requirement_ids: [],
      items: [
        {
          requirement: {
            id: "REQ-001",
            title: "登录成功",
            description: "登录成功",
            keywords: ["手机号", "验证码"],
            priority: "high",
            source: "frontend"
          },
          covered: true,
          coverage_score: 1,
          matched_case_ids: ["TC-001"],
          matched_case_titles: ["登录成功"],
          matched_keywords: ["手机号", "验证码"],
          missing_keywords: []
        }
      ],
      warnings: [],
      recommendations: ["继续补充异常场景"]
    };
    const api = {
      evaluateCoverage: vi.fn().mockResolvedValue(coverage)
    } as unknown as ApiClient;

    render(<CoveragePanel api={api} currentCases={cases} />);

    fireEvent.click(screen.getByRole("button", { name: "评估覆盖率" }));

    await waitFor(() =>
      expect(api.evaluateCoverage).toHaveBeenCalledWith(
        expect.arrayContaining([expect.objectContaining({ id: "REQ-001" })]),
        cases,
        1
      )
    );
    expect(await screen.findByText("匹配用例：TC-001")).toBeInTheDocument();
    expect(screen.getByText("继续补充异常场景")).toBeInTheDocument();
  });

  it("persists uncovered coverage gaps after manual confirmation", async () => {
    const coverage: CoverageEvaluationResponse = {
      total_requirements: 1,
      covered_requirements: 0,
      coverage_rate: 0,
      total_keywords: 2,
      matched_keywords: 1,
      keyword_coverage_rate: 0.5,
      uncovered_requirement_ids: ["REQ-002"],
      items: [
        {
          requirement: {
            id: "REQ-002",
            title: "验证码错误提示",
            description: "验证码错误时需要明确提示",
            keywords: ["验证码错误", "提示"],
            priority: "high",
            source: "frontend"
          },
          covered: false,
          coverage_score: 0.5,
          matched_case_ids: [],
          matched_case_titles: [],
          matched_keywords: ["验证码错误"],
          missing_keywords: ["提示"]
        }
      ],
      warnings: ["uncovered_requirements"],
      recommendations: ["补充未覆盖验收点对应的测试用例：REQ-002。"]
    };
    const api = {
      evaluateCoverage: vi.fn().mockResolvedValue(coverage),
      upsertCoverageGaps: vi.fn().mockResolvedValue({
        source: "knowledge/evaluation/coverage-gaps.md",
        version: 2,
        added_chunks: 1,
        replaced_chunks: 0,
        gap_count: 1,
        document_type: "evaluation",
        module: "coverage",
        tags: ["coverage-gap", "coverage"]
      })
    } as unknown as ApiClient;

    render(<CoveragePanel api={api} currentCases={cases} />);

    fireEvent.click(screen.getByRole("button", { name: "评估覆盖率" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认沉淀缺口" }));

    await waitFor(() =>
      expect(api.upsertCoverageGaps).toHaveBeenCalledWith(coverage, {
        source: "knowledge/evaluation/coverage-gaps.md",
        module: "coverage",
        tags: ["coverage-gap", "coverage"],
        chunk_size: 900
      })
    );
    expect(
      await screen.findByText("knowledge/evaluation/coverage-gaps.md v2 已沉淀 1 个缺口。")
    ).toBeInTheDocument();
  });
});
