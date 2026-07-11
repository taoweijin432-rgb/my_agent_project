import { BarChart3, CheckCircle2, History, Loader2, RefreshCw, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getErrorMessage, type ApiClient } from "../api/client";
import { formatDate, formatDuration, formatPercent } from "../api/format";
import type {
  GateStatus,
  GenerationRecordDetail,
  GenerationRecordSummary,
  RecordStatus,
  TestCase
} from "../api/types";
import { EmptyState, ErrorBanner, LoadingState, Metric, StatusBadge } from "./common";
import { ResultView } from "./ResultView";

interface HistoryPanelProps {
  api: ApiClient;
  onCasesReady: (cases: TestCase[]) => void;
  onOpenCoverage?: () => void;
}

export function HistoryPanel({ api, onCasesReady, onOpenCoverage }: HistoryPanelProps) {
  const [mode, setMode] = useState<"records" | "gates">("records");
  const [recordStatus, setRecordStatus] = useState<RecordStatus | "">("");
  const [gateStatus, setGateStatus] = useState<GateStatus | "all">("pending");
  const [records, setRecords] = useState<GenerationRecordSummary[]>([]);
  const [detail, setDetail] = useState<GenerationRecordDetail | null>(null);
  const [loading, setLoading] = useState<"list" | "detail" | "resolve" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resolvedBy, setResolvedBy] = useState("");
  const [comment, setComment] = useState("");

  const loadRecords = useCallback(async () => {
    setLoading("list");
    setError(null);
    try {
      const response =
        mode === "records"
          ? await api.listGenerationRecords({ limit: 50, offset: 0, status: recordStatus })
          : await api.listGenerationGates({ limit: 50, offset: 0, status: gateStatus });
      setRecords(response.records);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  }, [api, gateStatus, mode, recordStatus]);

  useEffect(() => {
    void loadRecords();
  }, [loadRecords]);

  const selectRecord = async (recordId: string) => {
    setLoading("detail");
    setError(null);
    try {
      const response = await api.getGenerationRecord(recordId);
      setDetail(response);
      if (response.response) {
        onCasesReady(response.response.cases);
      }
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const resolveGate = async (decision: "approved" | "rejected") => {
    if (!detail) {
      return;
    }
    setLoading("resolve");
    setError(null);
    try {
      const response = await api.resolveGenerationGate(detail.id, decision, resolvedBy, comment);
      setDetail(response);
      await loadRecords();
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const openCoverage = () => {
    if (!detail?.response) {
      return;
    }
    onCasesReady(detail.response.cases);
    onOpenCoverage?.();
  };

  return (
    <section className="page-grid two-column">
      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>生成历史</h2>
            <p>记录和门控共用历史存储。</p>
          </div>
          <button className="icon-button" type="button" title="刷新历史列表" onClick={loadRecords}>
            {loading === "list" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <RefreshCw size={18} aria-hidden="true" />
            )}
          </button>
        </div>

        <div className="filter-row">
          <div className="segmented">
            <button
              type="button"
              className={mode === "records" ? "active" : ""}
              onClick={() => setMode("records")}
            >
              记录
            </button>
            <button
              type="button"
              className={mode === "gates" ? "active" : ""}
              onClick={() => setMode("gates")}
            >
              门控
            </button>
          </div>
          {mode === "records" ? (
            <select
              value={recordStatus}
              onChange={(event) => setRecordStatus(event.target.value as RecordStatus | "")}
            >
              <option value="">全部</option>
              <option value="success">成功</option>
              <option value="failed">失败</option>
            </select>
          ) : (
            <select
              value={gateStatus}
              onChange={(event) => setGateStatus(event.target.value as GateStatus | "all")}
            >
              <option value="pending">待处理</option>
              <option value="approved">已批准</option>
              <option value="rejected">已驳回</option>
              <option value="all">全部</option>
            </select>
          )}
        </div>

        {error && <ErrorBanner message={error} />}

        <div className="record-list">
          {records.map((record) => (
            <button
              key={record.id}
              className="record-row"
              type="button"
              onClick={() => void selectRecord(record.id)}
            >
              <div>
                <strong>{record.description}</strong>
                <p>{formatDate(record.created_at)}</p>
              </div>
              <div className="record-meta">
                <StatusBadge status={record.status} />
                {record.gate_resolution && <StatusBadge status={record.gate_resolution.status} />}
                <span>{record.case_count} cases</span>
              </div>
            </button>
          ))}
          {records.length === 0 && <EmptyState icon={History} title="暂无历史记录" />}
        </div>
      </div>

      <div className="panel">
        {loading === "detail" && <LoadingState label="加载历史详情" />}
        {!detail && loading !== "detail" && <EmptyState icon={History} title="选择记录查看详情" />}
        {detail && loading !== "detail" && (
          <div className="detail-stack">
            <div className="detail-head">
              <div>
                <h2>{detail.id}</h2>
                <p>{detail.description}</p>
              </div>
              <StatusBadge status={detail.status} />
            </div>

            <div className="metric-grid">
              <Metric label="用例数" value={String(detail.case_count)} />
              <Metric label="耗时" value={formatDuration(detail.duration_ms)} />
              <Metric label="模型" value={detail.model || "-"} />
              <Metric label="Token" value={String(detail.usage.total_tokens_estimate)} />
            </div>

            {detail.quality && (
              <div className="quality-strip">
                <Metric label="质量分" value={String(detail.quality.score)} />
                <Metric label="评级" value={detail.quality.grade} />
                <Metric label="类型覆盖" value={formatPercent(detail.quality.type_coverage_rate)} />
              </div>
            )}

            {detail.gate && (
              <div className="gate-panel">
                <div>
                  <strong>{detail.gate.gate}</strong>
                  <p>{detail.gate.message}</p>
                  <p>{detail.gate.action_required}</p>
                </div>
                {detail.gate_resolution && <StatusBadge status={detail.gate_resolution.status} />}
              </div>
            )}

            {detail.gate && detail.gate_resolution?.status === "pending" && (
              <div className="resolve-panel">
                <div className="form-row">
                  <label>
                    <span>处理人</span>
                    <input value={resolvedBy} onChange={(event) => setResolvedBy(event.target.value)} />
                  </label>
                  <label>
                    <span>备注</span>
                    <input value={comment} onChange={(event) => setComment(event.target.value)} />
                  </label>
                </div>
                <div className="action-row">
                  <button
                    className="primary-button"
                    type="button"
                    disabled={loading === "resolve"}
                    onClick={() => void resolveGate("approved")}
                  >
                    <CheckCircle2 size={18} aria-hidden="true" />
                    <span>批准</span>
                  </button>
                  <button
                    className="danger-button"
                    type="button"
                    disabled={loading === "resolve"}
                    onClick={() => void resolveGate("rejected")}
                  >
                    <XCircle size={18} aria-hidden="true" />
                    <span>驳回</span>
                  </button>
                </div>
              </div>
            )}

            {detail.error && <ErrorBanner message={detail.error} />}

            {detail.response ? (
              <>
                {onOpenCoverage && (
                  <div className="action-row">
                    <button className="secondary-button" type="button" onClick={openCoverage}>
                      <BarChart3 size={18} aria-hidden="true" />
                      <span>覆盖率</span>
                    </button>
                  </div>
                )}
                <ResultView api={api} response={detail.response} />
              </>
            ) : (
              <EmptyState icon={History} title="该记录没有生成结果" />
            )}
          </div>
        )}
      </div>
    </section>
  );
}
