import { AlertCircle, ClipboardList, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getErrorMessage, type ApiClient } from "../api/client";
import { formatDate } from "../api/format";
import type { GenerationJobDetail, GenerationJobSummary, JobStatus, TestCase } from "../api/types";
import { EmptyState, ErrorBanner, LoadingState, Metric, StatusBadge } from "./common";
import { ResultView } from "./ResultView";

interface JobsPanelProps {
  api: ApiClient;
  onCasesReady: (cases: TestCase[]) => void;
}

export function JobsPanel({ api, onCasesReady }: JobsPanelProps) {
  const [status, setStatus] = useState<JobStatus | "">("");
  const [jobs, setJobs] = useState<GenerationJobSummary[]>([]);
  const [selectedJob, setSelectedJob] = useState<GenerationJobDetail | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadJobs = useCallback(async () => {
    setLoadingList(true);
    setError(null);
    try {
      const response = await api.listGenerationJobs({ limit: 50, offset: 0, status });
      setJobs(response.jobs);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoadingList(false);
    }
  }, [api, status]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  const selectJob = async (jobId: string) => {
    setLoadingDetail(true);
    setError(null);
    try {
      const detail = await api.getGenerationJob(jobId);
      setSelectedJob(detail);
      if (detail.response) {
        onCasesReady(detail.response.cases);
      }
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoadingDetail(false);
    }
  };

  return (
    <section className="page-grid two-column">
      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>异步任务</h2>
            <p>生成任务状态来自后端队列。</p>
          </div>
          <div className="panel-tools">
            <select value={status} onChange={(event) => setStatus(event.target.value as JobStatus | "")}>
              <option value="">全部</option>
              <option value="queued">排队</option>
              <option value="running">运行中</option>
              <option value="succeeded">成功</option>
              <option value="failed">失败</option>
            </select>
            <button className="icon-button" type="button" onClick={loadJobs} title="刷新任务列表">
              {loadingList ? (
                <Loader2 className="spin" size={18} aria-hidden="true" />
              ) : (
                <RefreshCw size={18} aria-hidden="true" />
              )}
            </button>
          </div>
        </div>

        {error && <ErrorBanner message={error} />}

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
              {jobs.map((job) => (
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
          {jobs.length === 0 && <EmptyState icon={ClipboardList} title="暂无任务" />}
        </div>
      </div>

      <div className="panel">
        {loadingDetail && <LoadingState label="加载任务详情" />}
        {!loadingDetail && selectedJob && (
          <JobDetail api={api} job={selectedJob} onCasesReady={onCasesReady} />
        )}
        {!loadingDetail && !selectedJob && <EmptyState icon={ClipboardList} title="选择任务查看详情" />}
      </div>
    </section>
  );
}

function JobDetail({
  api,
  job,
  onCasesReady
}: JobsPanelProps & { job: GenerationJobDetail }) {
  useEffect(() => {
    if (job.response) {
      onCasesReady(job.response.cases);
    }
  }, [job.response, onCasesReady]);

  return (
    <div className="detail-stack">
      <div className="detail-head">
        <div>
          <h2>{job.id}</h2>
          <p>{job.request.description}</p>
        </div>
        <StatusBadge status={job.status} />
      </div>

      <div className="metric-grid">
        <Metric label="创建时间" value={formatDate(job.created_at)} />
        <Metric label="更新时间" value={formatDate(job.updated_at)} />
        <Metric label="记录 ID" value={job.record_id || "-"} />
      </div>

      {job.error && (
        <div className="error-panel">
          <AlertCircle size={18} aria-hidden="true" />
          <div>
            <strong>{job.error.code}</strong>
            <p>{job.error.message}</p>
            {job.error.gate && <p>{job.error.gate.action_required}</p>}
          </div>
        </div>
      )}

      {job.response ? (
        <ResultView api={api} response={job.response} />
      ) : (
        <EmptyState icon={ClipboardList} title="任务暂无结果" />
      )}
    </div>
  );
}
