import { ClipboardList, Loader2, Play, Send, WandSparkles } from "lucide-react";
import { useState } from "react";

import { getErrorMessage, type ApiClient } from "../api/client";
import { normalizeGenerateRequest } from "../api/generate";
import {
  TEST_CASE_TYPE_OPTIONS,
  type GenerateRequest,
  type GenerateResponse,
  type GenerationJobDetail,
  type TestCase,
  type TestCaseType
} from "../api/types";
import { EmptyState, ErrorBanner, StatusBadge } from "./common";
import { ResultView } from "./ResultView";

const DEFAULT_GENERATE_REQUEST: GenerateRequest = {
  description:
    "用户使用手机号和验证码登录系统。验证码正确且未过期时登录成功，验证码错误或过期时提示失败，连续失败需要触发风控限制。",
  max_cases: 8,
  knowledge_top_k: 5,
  include_context: true,
  focus_types: ["functional", "boundary", "exception", "security"]
};

interface GeneratePanelProps {
  api: ApiClient;
  onCasesReady: (cases: TestCase[]) => void;
}

export function GeneratePanel({ api, onCasesReady }: GeneratePanelProps) {
  const [request, setRequest] = useState<GenerateRequest>(DEFAULT_GENERATE_REQUEST);
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [submittedJob, setSubmittedJob] = useState<GenerationJobDetail | null>(null);
  const [loading, setLoading] = useState<"sync" | "job" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const setRequestValue = <K extends keyof GenerateRequest>(key: K, value: GenerateRequest[K]) => {
    setRequest((current) => ({ ...current, [key]: value }));
  };

  const toggleFocusType = (type: TestCaseType) => {
    const selected = request.focus_types || [];
    const next = selected.includes(type)
      ? selected.filter((item) => item !== type)
      : [...selected, type];
    setRequestValue("focus_types", next.length > 0 ? next : null);
  };

  const runGenerate = async () => {
    setLoading("sync");
    setError(null);
    setSubmittedJob(null);
    try {
      const response = await api.generateTestCases(normalizeGenerateRequest(request));
      setResult(response);
      onCasesReady(response.cases);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const submitJob = async () => {
    setLoading("job");
    setError(null);
    try {
      const job = await api.submitGenerationJob(normalizeGenerateRequest(request));
      setSubmittedJob(job);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  return (
    <section className="page-grid generate-grid">
      <div className="panel generator-panel">
        <div className="panel-heading">
          <div>
            <h2>用例生成</h2>
            <p>当前请求会提交到后端生成链路。</p>
          </div>
        </div>

        <label className="field-block">
          <span>需求描述</span>
          <textarea
            className="description-input"
            value={request.description}
            onChange={(event) => setRequestValue("description", event.target.value)}
          />
        </label>

        <div className="form-row">
          <label>
            <span>最大用例数</span>
            <input
              type="number"
              min={1}
              max={50}
              value={request.max_cases}
              onChange={(event) => setRequestValue("max_cases", Number(event.target.value))}
            />
          </label>
          <label>
            <span>检索 Top K</span>
            <input
              type="number"
              min={0}
              max={10}
              value={request.knowledge_top_k}
              onChange={(event) => setRequestValue("knowledge_top_k", Number(event.target.value))}
            />
          </label>
          <label className="switch-field">
            <input
              type="checkbox"
              checked={request.include_context}
              onChange={(event) => setRequestValue("include_context", event.target.checked)}
            />
            <span>返回上下文</span>
          </label>
        </div>

        <div className="type-picker" aria-label="用例类型">
          {TEST_CASE_TYPE_OPTIONS.map((option) => (
            <label key={option.value} className="type-check">
              <input
                type="checkbox"
                checked={(request.focus_types || []).includes(option.value)}
                onChange={() => toggleFocusType(option.value)}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>

        {error && <ErrorBanner message={error} />}

        {submittedJob && (
          <div className="inline-notice">
            <ClipboardList size={18} aria-hidden="true" />
            <span>任务已提交：{submittedJob.id}</span>
            <StatusBadge status={submittedJob.status} />
          </div>
        )}

        <div className="action-row">
          <button
            className="primary-button"
            type="button"
            disabled={loading !== null}
            onClick={runGenerate}
          >
            {loading === "sync" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <Play size={18} aria-hidden="true" />
            )}
            <span>同步生成</span>
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={loading !== null}
            onClick={submitJob}
          >
            {loading === "job" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <Send size={18} aria-hidden="true" />
            )}
            <span>提交任务</span>
          </button>
        </div>
      </div>

      <div className="panel result-panel">
        {result ? (
          <ResultView api={api} response={result} />
        ) : (
          <EmptyState icon={WandSparkles} title="等待生成结果" />
        )}
      </div>
    </section>
  );
}
