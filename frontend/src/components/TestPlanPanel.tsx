import {
  AlertCircle,
  ClipboardList,
  Download,
  FileText,
  Loader2,
  Play,
  RefreshCw,
  Send,
  WandSparkles
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getErrorMessage, type ApiClient } from "../api/client";
import { downloadBlob } from "../api/download";
import { formatDate, formatPercent } from "../api/format";
import { parseRequirements } from "../api/requirements";
import {
  TEST_CASE_TYPE_OPTIONS,
  TEST_PLAN_PRIORITY_OPTIONS,
  TEST_TOOL_TYPE_OPTIONS,
  type JobStatus,
  type TestAgentWorkflowJobDetail,
  type TestAgentWorkflowJobSummary,
  type TestExecutionReport,
  type TestPlan,
  type TestPlanExecutionJobDetail,
  type TestPlanExecutionJobSummary,
  type TestPlanGenerationRequest,
  type TestPlanPriority,
  type TestReportExportFormat,
  type TestToolType
} from "../api/types";
import { EmptyState, ErrorBanner, Metric, StatusBadge, TagList, TextList } from "./common";

interface TestPlanPanelProps {
  api: ApiClient;
}

type LoadingAction =
  | "generate"
  | "execute"
  | "submit"
  | "workflow-submit"
  | "workflow-jobs"
  | "workflow-detail"
  | "jobs"
  | "detail"
  | "export-markdown"
  | "export-json"
  | null;

const DEFAULT_DESCRIPTION =
  "用户使用手机号和验证码登录系统。验证码正确且未过期时登录成功，验证码错误或过期时提示失败，连续失败需要触发风控限制。";
const DEFAULT_REQUIREMENTS =
  "REQ-001|验证码正确且未过期时登录成功|手机号,验证码,登录成功|high\n" +
  "REQ-002|验证码错误或过期时提示失败|验证码错误,过期,失败提示|high";

export function TestPlanPanel({ api }: TestPlanPanelProps) {
  const [description, setDescription] = useState(DEFAULT_DESCRIPTION);
  const [source, setSource] = useState("frontend/test-plan");
  const [requirementsText, setRequirementsText] = useState(DEFAULT_REQUIREMENTS);
  const [maxSteps, setMaxSteps] = useState(8);
  const [useLlm, setUseLlm] = useState(false);
  const [allowLlmFallback, setAllowLlmFallback] = useState(true);
  const [httpBaseUrl, setHttpBaseUrl] = useState("http://testserver");
  const [plan, setPlan] = useState<TestPlan | null>(null);
  const [report, setReport] = useState<TestExecutionReport | null>(null);
  const [executionJobs, setExecutionJobs] = useState<TestPlanExecutionJobSummary[]>([]);
  const [workflowJobs, setWorkflowJobs] = useState<TestAgentWorkflowJobSummary[]>([]);
  const [executionStatus, setExecutionStatus] = useState<JobStatus | "">("");
  const [workflowStatus, setWorkflowStatus] = useState<JobStatus | "">("");
  const [selectedJob, setSelectedJob] = useState<TestPlanExecutionJobDetail | null>(null);
  const [submittedJob, setSubmittedJob] = useState<TestPlanExecutionJobDetail | null>(null);
  const [selectedWorkflowJob, setSelectedWorkflowJob] = useState<TestAgentWorkflowJobDetail | null>(null);
  const [submittedWorkflowJob, setSubmittedWorkflowJob] = useState<TestAgentWorkflowJobDetail | null>(null);
  const [loading, setLoading] = useState<LoadingAction>(null);
  const [error, setError] = useState<string | null>(null);

  const loadExecutionJobs = useCallback(async () => {
    setLoading((current) => current || "jobs");
    setError(null);
    try {
      const response = await api.listTestPlanExecutionJobs({
        limit: 50,
        offset: 0,
        status: executionStatus
      });
      setExecutionJobs(response.jobs);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading((current) => (current === "jobs" ? null : current));
    }
  }, [api, executionStatus]);

  const loadWorkflowJobs = useCallback(async () => {
    setLoading((current) => current || "workflow-jobs");
    setError(null);
    try {
      const response = await api.listTestAgentWorkflowJobs({
        limit: 50,
        offset: 0,
        status: workflowStatus
      });
      setWorkflowJobs(response.jobs);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading((current) => (current === "workflow-jobs" ? null : current));
    }
  }, [api, workflowStatus]);

  useEffect(() => {
    void loadExecutionJobs();
  }, [loadExecutionJobs]);

  useEffect(() => {
    void loadWorkflowJobs();
  }, [loadWorkflowJobs]);

  const generatePlan = async () => {
    setLoading("generate");
    setError(null);
    setSubmittedJob(null);
    setSubmittedWorkflowJob(null);
    try {
      const generated = await api.generateTestPlan(buildGenerationRequest());
      setPlan(generated);
      setReport(null);
      setSelectedJob(null);
      setSelectedWorkflowJob(null);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const executePlan = async () => {
    if (!plan) {
      setError("请先生成测试计划。");
      return;
    }
    setLoading("execute");
    setError(null);
    try {
      const executionReport = await api.executeTestPlan({
        plan,
        http_base_url: httpBaseUrl.trim()
      });
      setReport(executionReport);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const submitExecutionJob = async () => {
    if (!plan) {
      setError("请先生成测试计划。");
      return;
    }
    setLoading("submit");
    setError(null);
    try {
      const job = await api.submitTestPlanExecutionJob({
        plan,
        http_base_url: httpBaseUrl.trim()
      });
      setSubmittedJob(job);
      setSelectedJob(job);
      setSelectedWorkflowJob(null);
      await loadExecutionJobs();
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const hydrateWorkflowResult = (job: TestAgentWorkflowJobDetail) => {
    if (!job.result) {
      return;
    }
    setPlan(job.result.plan);
    setReport(job.result.report);
    setSelectedJob(null);
  };

  const submitWorkflowJob = async () => {
    setLoading("workflow-submit");
    setError(null);
    setSubmittedJob(null);
    try {
      const job = await api.submitTestAgentWorkflowJob({
        generation_request: buildGenerationRequest(),
        http_base_url: httpBaseUrl.trim()
      });
      setSubmittedWorkflowJob(job);
      setSelectedWorkflowJob(job);
      hydrateWorkflowResult(job);
      await loadWorkflowJobs();
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const selectJob = async (jobId: string) => {
    setLoading("detail");
    setError(null);
    try {
      const detail = await api.getTestPlanExecutionJob(jobId);
      setSelectedJob(detail);
      setSelectedWorkflowJob(null);
      setPlan(detail.request.plan);
      if (detail.report) {
        setReport(detail.report);
      }
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const refreshWorkflowJob = useCallback(
    async (jobId: string) => {
      try {
        const detail = await api.getTestAgentWorkflowJob(jobId);
        setSelectedWorkflowJob(detail);
        setSubmittedWorkflowJob((current) => (current?.id === detail.id ? detail : current));
        hydrateWorkflowResult(detail);
        await loadWorkflowJobs();
      } catch (caught) {
        setError(getErrorMessage(caught));
      }
    },
    [api, loadWorkflowJobs]
  );

  const selectWorkflowJob = async (jobId: string) => {
    setLoading("workflow-detail");
    setError(null);
    try {
      await refreshWorkflowJob(jobId);
    } finally {
      setLoading(null);
    }
  };

  const activeWorkflowJobId =
    selectedWorkflowJob && isActiveJobStatus(selectedWorkflowJob.status)
      ? selectedWorkflowJob.id
      : submittedWorkflowJob && isActiveJobStatus(submittedWorkflowJob.status)
        ? submittedWorkflowJob.id
        : null;

  useEffect(() => {
    if (!activeWorkflowJobId) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      void refreshWorkflowJob(activeWorkflowJobId);
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [activeWorkflowJobId, refreshWorkflowJob]);

  const exportReport = async (format: TestReportExportFormat) => {
    if (!report) {
      setError("暂无可导出的执行报告。");
      return;
    }
    const action = format === "json" ? "export-json" : "export-markdown";
    const extension = format === "json" ? "json" : "md";
    const filename = `${report.id}.${extension}`;
    setLoading(action);
    setError(null);
    try {
      const blob = await api.exportTestPlanReport(report, { format, filename });
      downloadBlob(blob, filename);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const buildGenerationRequest = (): TestPlanGenerationRequest => ({
    description: description.trim(),
    source: source.trim() || null,
    requirements: parseRequirements(requirementsText),
    context: [],
    max_steps: maxSteps,
    use_llm: useLlm,
    allow_llm_fallback: allowLlmFallback
  });

  return (
    <section className="page-grid test-plan-grid">
      <div className="panel generator-panel">
        <div className="panel-heading">
          <div>
            <h2>测试计划</h2>
            <p>需求会生成结构化计划，再进入执行链路。</p>
          </div>
        </div>

        <label className="field-block">
          <span>需求描述</span>
          <textarea
            className="description-input"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>

        <label className="field-block">
          <span>需求点</span>
          <textarea
            className="plan-requirements-input"
            value={requirementsText}
            onChange={(event) => setRequirementsText(event.target.value)}
          />
        </label>

        <div className="form-row">
          <label>
            <span>来源</span>
            <input value={source} onChange={(event) => setSource(event.target.value)} />
          </label>
          <label>
            <span>最大步骤数</span>
            <input
              type="number"
              min={1}
              max={50}
              value={maxSteps}
              onChange={(event) => setMaxSteps(Number(event.target.value))}
            />
          </label>
          <label>
            <span>HTTP Base URL</span>
            <input
              value={httpBaseUrl}
              onChange={(event) => setHttpBaseUrl(event.target.value)}
              spellCheck={false}
            />
          </label>
        </div>

        <div className="form-row compact-form-row">
          <label className="switch-field">
            <input
              type="checkbox"
              checked={useLlm}
              onChange={(event) => setUseLlm(event.target.checked)}
            />
            <span>使用 LLM</span>
          </label>
          <label className="switch-field">
            <input
              type="checkbox"
              checked={allowLlmFallback}
              onChange={(event) => setAllowLlmFallback(event.target.checked)}
            />
            <span>允许 fallback</span>
          </label>
        </div>

        {error && <ErrorBanner message={error} />}

        {submittedJob && (
          <div className="inline-notice">
            <ClipboardList size={18} aria-hidden="true" />
            <span>执行任务已提交：{submittedJob.id}</span>
            <StatusBadge status={submittedJob.status} />
          </div>
        )}

        {submittedWorkflowJob && (
          <div className="inline-notice">
            <ClipboardList size={18} aria-hidden="true" />
            <span>Workflow 任务已提交：{submittedWorkflowJob.id}</span>
            <StatusBadge status={submittedWorkflowJob.status} />
          </div>
        )}

        <div className="action-row">
          <button
            className="primary-button"
            type="button"
            disabled={loading !== null}
            onClick={generatePlan}
          >
            {loading === "generate" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <WandSparkles size={18} aria-hidden="true" />
            )}
            <span>生成计划</span>
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={loading !== null}
            onClick={submitWorkflowJob}
          >
            {loading === "workflow-submit" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <Send size={18} aria-hidden="true" />
            )}
            <span>提交完整任务</span>
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={loading !== null || !plan}
            onClick={executePlan}
          >
            {loading === "execute" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <Play size={18} aria-hidden="true" />
            )}
            <span>同步执行</span>
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={loading !== null || !plan}
            onClick={submitExecutionJob}
          >
            {loading === "submit" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <Send size={18} aria-hidden="true" />
            )}
            <span>提交执行任务</span>
          </button>
        </div>
      </div>

      <div className="panel">
        {plan ? <TestPlanView plan={plan} /> : <EmptyState icon={FileText} title="等待测试计划" />}
        {report && (
          <ExecutionReportView
            report={report}
            loading={loading}
            onExport={exportReport}
          />
        )}
      </div>

      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>Workflow 任务</h2>
            <p>从需求生成计划、执行工具并汇总报告。</p>
          </div>
          <div className="panel-tools">
            <select
              value={workflowStatus}
              onChange={(event) => setWorkflowStatus(event.target.value as JobStatus | "")}
            >
              <option value="">全部</option>
              <option value="queued">排队</option>
              <option value="running">运行中</option>
              <option value="succeeded">成功</option>
              <option value="failed">失败</option>
            </select>
            <button
              className="icon-button"
              type="button"
              onClick={loadWorkflowJobs}
              title="刷新 Workflow 任务"
            >
              {loading === "workflow-jobs" ? (
                <Loader2 className="spin" size={18} aria-hidden="true" />
              ) : (
                <RefreshCw size={18} aria-hidden="true" />
              )}
            </button>
          </div>
        </div>

        <div className="table-wrap compact-list">
          <table>
            <thead>
              <tr>
                <th>任务 ID</th>
                <th>状态</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {workflowJobs.map((job) => (
                <tr
                  key={job.id}
                  className="clickable-row"
                  onClick={() => void selectWorkflowJob(job.id)}
                >
                  <td>{job.id}</td>
                  <td>
                    <StatusBadge status={job.status} />
                  </td>
                  <td>{formatDate(job.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {workflowJobs.length === 0 && <EmptyState icon={ClipboardList} title="暂无 Workflow 任务" />}
        </div>
      </div>

      <div className="panel">
        {loading === "workflow-detail" && (
          <div className="empty-state">
            <Loader2 className="spin" size={30} aria-hidden="true" />
            <span>加载 Workflow 详情</span>
          </div>
        )}
        {loading !== "workflow-detail" && selectedWorkflowJob && (
          <WorkflowJobDetail
            job={selectedWorkflowJob}
            loading={loading}
            onExport={exportReport}
          />
        )}
        {loading !== "workflow-detail" && !selectedWorkflowJob && (
          <EmptyState icon={ClipboardList} title="选择 Workflow 任务查看详情" />
        )}
      </div>

      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>执行任务</h2>
            <p>测试计划执行 job 状态来自后端队列。</p>
          </div>
          <div className="panel-tools">
            <select
              value={executionStatus}
              onChange={(event) => setExecutionStatus(event.target.value as JobStatus | "")}
            >
              <option value="">全部</option>
              <option value="queued">排队</option>
              <option value="running">运行中</option>
              <option value="succeeded">成功</option>
              <option value="failed">失败</option>
            </select>
            <button
              className="icon-button"
              type="button"
              onClick={loadExecutionJobs}
              title="刷新执行任务"
            >
              {loading === "jobs" ? (
                <Loader2 className="spin" size={18} aria-hidden="true" />
              ) : (
                <RefreshCw size={18} aria-hidden="true" />
              )}
            </button>
          </div>
        </div>

        <div className="table-wrap compact-list">
          <table>
            <thead>
              <tr>
                <th>任务 ID</th>
                <th>状态</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {executionJobs.map((job) => (
                <tr key={job.id} className="clickable-row" onClick={() => void selectJob(job.id)}>
                  <td>{job.id}</td>
                  <td>
                    <StatusBadge status={job.status} />
                  </td>
                  <td>{formatDate(job.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {executionJobs.length === 0 && <EmptyState icon={ClipboardList} title="暂无执行任务" />}
        </div>
      </div>

      <div className="panel">
        {loading === "detail" && (
          <div className="empty-state">
            <Loader2 className="spin" size={30} aria-hidden="true" />
            <span>加载执行详情</span>
          </div>
        )}
        {loading !== "detail" && selectedJob && (
          <ExecutionJobDetail
            job={selectedJob}
            loading={loading}
            onExport={exportReport}
          />
        )}
        {loading !== "detail" && !selectedJob && (
          <EmptyState icon={ClipboardList} title="选择执行任务查看详情" />
        )}
      </div>
    </section>
  );
}

function isActiveJobStatus(status: JobStatus): boolean {
  return status === "queued" || status === "running";
}

function TestPlanView({ plan }: { plan: TestPlan }) {
  const automatedSteps = plan.steps.filter((step) => step.tool !== "manual").length;

  return (
    <div className="detail-stack test-plan-view">
      <div className="detail-head">
        <div>
          <h2>{plan.title}</h2>
          <p>{plan.source || plan.id}</p>
        </div>
      </div>

      <div className="metric-grid">
        <Metric label="需求点" value={String(plan.requirements.length)} />
        <Metric label="步骤数" value={String(plan.steps.length)} />
        <Metric label="自动化步骤" value={String(automatedSteps)} />
        <Metric label="风险数" value={String(plan.scope.risks.length)} />
      </div>

      <div className="scope-grid">
        <TextList title="范围" items={plan.scope.in_scope} />
        <TextList title="风险" items={plan.scope.risks} />
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>步骤</th>
              <th>标题</th>
              <th>工具</th>
              <th>优先级</th>
              <th>类型</th>
              <th>需求</th>
            </tr>
          </thead>
          <tbody>
            {plan.steps.map((step) => (
              <tr key={step.id}>
                <td>{step.id}</td>
                <td>
                  <strong>{step.title}</strong>
                  <p className="table-subtext">{step.objective}</p>
                </td>
                <td>{toolLabel(step.tool)}</td>
                <td>{priorityLabel(step.priority)}</td>
                <td>
                  <TagList tags={step.test_types.map(typeLabel)} />
                </td>
                <td>
                  <TagList tags={step.requirement_ids} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ExecutionReportView({
  report,
  loading,
  onExport
}: {
  report: TestExecutionReport;
  loading: LoadingAction;
  onExport: (format: TestReportExportFormat) => void;
}) {
  const covered = Object.values(report.requirement_coverage).filter(Boolean).length;
  const total = Object.keys(report.requirement_coverage).length;
  const coverageRate = total === 0 ? 0 : covered / total;

  return (
    <div className="detail-stack execution-report">
      <div className="detail-head">
        <div>
          <h2>执行报告</h2>
          <p>{report.summary || report.id}</p>
        </div>
        <div className="report-actions">
          <StatusBadge status={report.status} />
          <button
            className="icon-button"
            type="button"
            onClick={() => onExport("markdown")}
            disabled={loading !== null}
            title="导出 Markdown 报告"
            aria-label="导出 Markdown 报告"
          >
            {loading === "export-markdown" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <Download size={18} aria-hidden="true" />
            )}
          </button>
          <button
            className="secondary-button compact-button"
            type="button"
            onClick={() => onExport("json")}
            disabled={loading !== null}
          >
            {loading === "export-json" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <FileText size={18} aria-hidden="true" />
            )}
            <span>JSON</span>
          </button>
        </div>
      </div>

      <div className="metric-grid">
        <Metric label="工具运行" value={String(report.tool_runs.length)} />
        <Metric label="需求覆盖" value={formatPercent(coverageRate)} />
        <Metric label="缺陷" value={String(report.defects.length)} />
        <Metric label="建议" value={String(report.recommendations.length)} />
      </div>

      <div className="table-wrap compact-list">
        <table>
          <thead>
            <tr>
              <th>Run ID</th>
              <th>步骤</th>
              <th>工具</th>
              <th>状态</th>
              <th>输出</th>
            </tr>
          </thead>
          <tbody>
            {report.tool_runs.map((run) => (
              <tr key={run.id}>
                <td>{run.id}</td>
                <td>{run.plan_step_id}</td>
                <td>{toolLabel(run.tool)}</td>
                <td>
                  <StatusBadge status={run.status} />
                </td>
                <td>
                  {run.output_summary || "-"}
                  <TagList tags={run.artifact_paths} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {report.tool_runs.length === 0 && <EmptyState icon={ClipboardList} title="暂无工具运行" />}
      </div>

      <div className="scope-grid">
        <TextList title="缺陷" items={report.defects} />
        <TextList title="建议" items={report.recommendations} />
      </div>
    </div>
  );
}

function ExecutionJobDetail({
  job,
  loading,
  onExport
}: {
  job: TestPlanExecutionJobDetail;
  loading: LoadingAction;
  onExport: (format: TestReportExportFormat) => void;
}) {
  return (
    <div className="detail-stack">
      <div className="detail-head">
        <div>
          <h2>{job.id}</h2>
          <p>{job.request.plan.title}</p>
        </div>
        <StatusBadge status={job.status} />
      </div>

      <div className="metric-grid">
        <Metric label="创建时间" value={formatDate(job.created_at)} />
        <Metric label="更新时间" value={formatDate(job.updated_at)} />
        <Metric label="开始时间" value={formatDate(job.started_at)} />
        <Metric label="完成时间" value={formatDate(job.finished_at)} />
      </div>

      {job.error && (
        <div className="error-panel">
          <AlertCircle size={18} aria-hidden="true" />
          <div>
            <strong>{job.error.code}</strong>
            <p>{job.error.message}</p>
          </div>
        </div>
      )}

      {job.report ? (
        <ExecutionReportView report={job.report} loading={loading} onExport={onExport} />
      ) : (
        <EmptyState icon={ClipboardList} title="任务暂无报告" />
      )}
    </div>
  );
}

function WorkflowJobDetail({
  job,
  loading,
  onExport
}: {
  job: TestAgentWorkflowJobDetail;
  loading: LoadingAction;
  onExport: (format: TestReportExportFormat) => void;
}) {
  const llmMetrics = getWorkflowLlmMetrics(job);

  return (
    <div className="detail-stack">
      <div className="detail-head">
        <div>
          <h2>{job.id}</h2>
          <p>{job.request.generation_request.description}</p>
        </div>
        <StatusBadge status={job.status} />
      </div>

      <div className="metric-grid">
        <Metric label="创建时间" value={formatDate(job.created_at)} />
        <Metric label="更新时间" value={formatDate(job.updated_at)} />
        <Metric label="开始时间" value={formatDate(job.started_at)} />
        <Metric label="完成时间" value={formatDate(job.finished_at)} />
        <Metric label="排队耗时" value={formatDurationMs(job.timing.queue_wait_ms)} />
        <Metric label="任务耗时" value={formatDurationMs(job.timing.job_runtime_ms)} />
        <Metric label="计划生成" value={formatDurationMs(job.timing.plan_generation_ms)} />
        <Metric label="工具执行" value={formatDurationMs(job.timing.tool_execution_ms)} />
        <Metric label="报告汇总" value={formatDurationMs(job.timing.report_build_ms)} />
        {llmMetrics && (
          <>
            <Metric label="LLM尝试" value={formatOptionalNumber(llmMetrics.attemptCount)} />
            <Metric label="LLM重试" value={formatOptionalNumber(llmMetrics.retryCount)} />
            <Metric label="LLM总耗时" value={formatDurationMs(llmMetrics.totalDurationMs)} />
            <Metric label="LLM缓存" value={llmMetrics.cacheStatus || "-"} />
            <Metric label="LLM状态" value={llmMetrics.lastStatus || "-"} />
            <Metric label="LLM兜底" value={llmMetrics.usedFallback ? "是" : "否"} />
          </>
        )}
      </div>

      {job.error && (
        <div className="error-panel">
          <AlertCircle size={18} aria-hidden="true" />
          <div>
            <strong>{job.error.code}</strong>
            <p>{job.error.message}</p>
          </div>
        </div>
      )}

      {job.result ? (
        <>
          <TestPlanView plan={job.result.plan} />
          <ExecutionReportView report={job.result.report} loading={loading} onExport={onExport} />
        </>
      ) : (
        <EmptyState icon={ClipboardList} title="任务暂无结果" />
      )}
    </div>
  );
}

function priorityLabel(priority: TestPlanPriority): string {
  return TEST_PLAN_PRIORITY_OPTIONS.find((option) => option.value === priority)?.label || priority;
}

function toolLabel(tool: TestToolType): string {
  return TEST_TOOL_TYPE_OPTIONS.find((option) => option.value === tool)?.label || tool;
}

function typeLabel(type: string): string {
  return TEST_CASE_TYPE_OPTIONS.find((option) => option.value === type)?.label || type;
}

interface WorkflowLlmMetrics {
  attemptCount: number | null;
  retryCount: number | null;
  totalDurationMs: number | null;
  cacheStatus: string | null;
  lastStatus: string | null;
  usedFallback: boolean;
}

function getWorkflowLlmMetrics(job: TestAgentWorkflowJobDetail): WorkflowLlmMetrics | null {
  const timing = job.result?.timing ?? job.error?.timing;
  const planGeneration = timing?.stages.find(
    (stage) => stage.name === "plan_generation"
  );
  const details = planGeneration?.details;
  if (!isRecord(details) || details.used_llm !== true) {
    return null;
  }

  const llm = isRecord(details.llm) ? details.llm : {};
  return {
    attemptCount: optionalNumber(llm.attempt_count),
    retryCount: optionalNumber(llm.retry_count),
    totalDurationMs: optionalNumber(llm.total_duration_ms),
    cacheStatus: optionalString(details.cache_status),
    lastStatus: optionalString(llm.last_status),
    usedFallback: details.used_fallback === true
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function formatOptionalNumber(value: number | null): string {
  return value === null ? "-" : String(value);
}

function formatDurationMs(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)}s`;
  }
  return `${Math.round(value)}ms`;
}
