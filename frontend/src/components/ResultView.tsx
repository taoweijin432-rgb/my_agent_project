import { FileCode2, FileSpreadsheet, Loader2 } from "lucide-react";
import { useState } from "react";

import { getErrorMessage, type ApiClient } from "../api/client";
import { downloadBlob } from "../api/download";
import { getTypeLabel } from "../api/format";
import type { GenerateResponse, TestCase } from "../api/types";
import {
  ChunkList,
  ErrorBanner,
  Metric,
  OrderedInlineList,
  StatusBadge,
  TextList
} from "./common";

interface ResultViewProps {
  api: ApiClient;
  response: GenerateResponse;
}

export function ResultView({ api, response }: ResultViewProps) {
  const [exporting, setExporting] = useState<"excel" | "pytest" | null>(null);
  const [exportBaseName, setExportBaseName] = useState("test-cases");
  const [error, setError] = useState<string | null>(null);

  const exportExcel = async () => {
    setExporting("excel");
    setError(null);
    try {
      const blob = await api.exportExcel(response.cases, `${exportBaseName}.xlsx`);
      downloadBlob(blob, `${exportBaseName}.xlsx`);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setExporting(null);
    }
  };

  const exportPytest = async () => {
    setExporting("pytest");
    setError(null);
    try {
      const blob = await api.exportPytest(response.cases, {
        filename: `${exportBaseName}.py`
      });
      downloadBlob(blob, `${exportBaseName}.py`);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="result-stack">
      <div className="result-head">
        <div>
          <h2>生成结果</h2>
          <p>
            {response.cases.length} 条用例 · {response.metadata.model} ·{" "}
            {response.metadata.workflow_backend || "workflow"}
          </p>
        </div>
        {response.metadata.review && (
          <div className="score-pill">
            <span>{response.metadata.review.score}</span>
            <small>{response.metadata.review.grade}</small>
          </div>
        )}
      </div>

      <div className="metric-grid">
        <Metric label="尝试次数" value={String(response.metadata.attempts)} />
        <Metric label="检索片段" value={String(response.metadata.retrieved_chunks)} />
        <Metric label="Token 估算" value={String(response.metadata.usage.total_tokens_estimate)} />
        <Metric
          label="成本"
          value={
            response.metadata.usage.estimated_cost === null
              ? "-"
              : `${response.metadata.usage.estimated_cost} ${response.metadata.usage.currency || ""}`
          }
        />
      </div>

      {response.metadata.review && (
        <div className="review-panel">
          <div className="review-line">
            <StatusBadge status={response.metadata.review.passed ? "success" : "failed"} />
            <span>Reviewer：{response.metadata.review.retry_recommended ? "建议重试" : "无需重试"}</span>
          </div>
          {response.metadata.review.warnings.length > 0 && (
            <TextList title="警告" items={response.metadata.review.warnings} />
          )}
          {response.metadata.review.recommendations.length > 0 && (
            <TextList title="建议" items={response.metadata.review.recommendations} />
          )}
        </div>
      )}

      <div className="export-row">
        <input
          value={exportBaseName}
          onChange={(event) => setExportBaseName(event.target.value)}
          aria-label="导出文件名"
        />
        <button className="secondary-button" type="button" disabled={exporting !== null} onClick={exportExcel}>
          {exporting === "excel" ? (
            <Loader2 className="spin" size={18} aria-hidden="true" />
          ) : (
            <FileSpreadsheet size={18} aria-hidden="true" />
          )}
          <span>Excel</span>
        </button>
        <button className="secondary-button" type="button" disabled={exporting !== null} onClick={exportPytest}>
          {exporting === "pytest" ? (
            <Loader2 className="spin" size={18} aria-hidden="true" />
          ) : (
            <FileCode2 size={18} aria-hidden="true" />
          )}
          <span>pytest</span>
        </button>
      </div>

      {error && <ErrorBanner message={error} />}

      <CaseTable cases={response.cases} />

      {response.retrieved_context.length > 0 && (
        <div className="context-panel">
          <h3>检索上下文</h3>
          <ChunkList chunks={response.retrieved_context} />
        </div>
      )}
    </div>
  );
}

function CaseTable({ cases }: { cases: TestCase[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>标题</th>
            <th>类型</th>
            <th>前置条件</th>
            <th>步骤</th>
            <th>预期</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((testCase) => (
            <tr key={testCase.id}>
              <td>{testCase.id}</td>
              <td>{testCase.title}</td>
              <td>{getTypeLabel(testCase.type)}</td>
              <td>{testCase.precondition || "-"}</td>
              <td>
                <OrderedInlineList items={testCase.steps} />
              </td>
              <td>
                <OrderedInlineList items={testCase.expected} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
