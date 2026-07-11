import { BarChart3, Database, Loader2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { getErrorMessage, type ApiClient } from "../api/client";
import { formatPercent } from "../api/format";
import { parseRequirements } from "../api/requirements";
import type { CoverageEvaluationResponse, TestCase } from "../api/types";
import {
  EmptyState,
  ErrorBanner,
  Metric,
  StatusBadge,
  SuccessBanner,
  TagList,
  TextList
} from "./common";

interface CoveragePanelProps {
  api: ApiClient;
  currentCases: TestCase[];
}

export function CoveragePanel({ api, currentCases }: CoveragePanelProps) {
  const [requirementText, setRequirementText] = useState(
    "REQ-001 | 登录成功 | 手机号,验证码,登录成功 | high\nREQ-002 | 验证码错误提示 | 验证码错误,提示 | high\nREQ-003 | 连续失败风控 | 连续失败,风控,限制 | critical"
  );
  const [minRatio, setMinRatio] = useState(1);
  const [result, setResult] = useState<CoverageEvaluationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [gapSource, setGapSource] = useState("knowledge/evaluation/coverage-gaps.md");
  const [gapModule, setGapModule] = useState("coverage");
  const [savingGaps, setSavingGaps] = useState(false);
  const [gapError, setGapError] = useState<string | null>(null);
  const [gapMessage, setGapMessage] = useState<string | null>(null);

  const uncoveredCount = result?.items.filter((item) => !item.covered).length ?? 0;

  const evaluate = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setGapError(null);
    setGapMessage(null);
    try {
      if (currentCases.length === 0) {
        throw new Error("当前会话没有可评估的测试用例。");
      }
      const requirements = parseRequirements(requirementText);
      if (requirements.length === 0) {
        throw new Error("请至少填写一个需求点。");
      }
      const response = await api.evaluateCoverage(requirements, currentCases, minRatio);
      setResult(response);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  const persistGaps = async () => {
    if (!result) {
      return;
    }
    setSavingGaps(true);
    setGapError(null);
    setGapMessage(null);
    try {
      const moduleName = gapModule.trim() || "coverage";
      const response = await api.upsertCoverageGaps(result, {
        source: gapSource.trim() || "knowledge/evaluation/coverage-gaps.md",
        module: moduleName,
        tags: ["coverage-gap", moduleName],
        chunk_size: 900
      });
      setGapMessage(`${response.source} v${response.version} 已沉淀 ${response.gap_count} 个缺口。`);
    } catch (caught) {
      setGapError(getErrorMessage(caught));
    } finally {
      setSavingGaps(false);
    }
  };

  return (
    <section className="page-grid coverage-grid">
      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>需求覆盖率</h2>
            <p>当前可评估用例数：{currentCases.length}</p>
          </div>
        </div>
        <form className="stack-form" onSubmit={evaluate}>
          <label className="field-block">
            <span>需求点</span>
            <textarea
              className="coverage-input"
              value={requirementText}
              onChange={(event) => setRequirementText(event.target.value)}
            />
          </label>
          <label>
            <span>关键词匹配阈值</span>
            <input
              type="number"
              min={0.1}
              max={1}
              step={0.1}
              value={minRatio}
              onChange={(event) => setMinRatio(Number(event.target.value))}
            />
          </label>
          {error && <ErrorBanner message={error} />}
          <button className="primary-button" type="submit" disabled={loading}>
            {loading ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <BarChart3 size={18} aria-hidden="true" />
            )}
            <span>评估覆盖率</span>
          </button>
        </form>
      </div>

      <div className="panel">
        {result ? (
          <div className="detail-stack">
            <div className="metric-grid">
              <Metric label="需求覆盖" value={formatPercent(result.coverage_rate)} />
              <Metric label="关键词覆盖" value={formatPercent(result.keyword_coverage_rate)} />
              <Metric
                label="覆盖需求"
                value={`${result.covered_requirements}/${result.total_requirements}`}
              />
              <Metric label="匹配关键词" value={`${result.matched_keywords}/${result.total_keywords}`} />
            </div>

            {result.warnings.length > 0 && <TextList title="警告" items={result.warnings} />}
            {result.recommendations.length > 0 && (
              <TextList title="建议" items={result.recommendations} />
            )}

            {uncoveredCount > 0 && (
              <div className="gap-save-panel">
                <div className="gap-save-head">
                  <strong>缺口沉淀</strong>
                  <span>{uncoveredCount} 个未覆盖需求</span>
                </div>
                <div className="gap-save-grid">
                  <label>
                    <span>知识库 source</span>
                    <input
                      aria-label="缺口知识库 source"
                      value={gapSource}
                      onChange={(event) => setGapSource(event.target.value)}
                      spellCheck={false}
                    />
                  </label>
                  <label>
                    <span>模块</span>
                    <input
                      aria-label="缺口模块"
                      value={gapModule}
                      onChange={(event) => setGapModule(event.target.value)}
                      spellCheck={false}
                    />
                  </label>
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={savingGaps}
                    onClick={persistGaps}
                  >
                    {savingGaps ? (
                      <Loader2 className="spin" size={18} aria-hidden="true" />
                    ) : (
                      <Database size={18} aria-hidden="true" />
                    )}
                    <span>确认沉淀缺口</span>
                  </button>
                </div>
                {gapError && <ErrorBanner message={gapError} />}
                {gapMessage && <SuccessBanner message={gapMessage} />}
              </div>
            )}

            <div className="coverage-list">
              {result.items.map((item) => (
                <div key={item.requirement.id} className="coverage-row">
                  <div>
                    <strong>
                      {item.requirement.id} · {item.requirement.title}
                    </strong>
                    <p>匹配用例：{item.matched_case_ids.join(", ") || "-"}</p>
                    <TagList tags={item.matched_keywords} />
                  </div>
                  <StatusBadge status={item.covered ? "success" : "failed"} />
                </div>
              ))}
            </div>
          </div>
        ) : (
          <EmptyState icon={BarChart3} title="等待覆盖率结果" />
        )}
      </div>
    </section>
  );
}
