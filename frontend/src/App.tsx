import {
  BarChart3,
  CheckCircle2,
  ClipboardList,
  Database,
  History,
  KeyRound,
  Loader2,
  Save,
  ShieldCheck,
  WandSparkles,
  XCircle
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { ApiClient, getErrorMessage, type ApiConfig } from "./api/client";
import { loadApiConfig, saveApiConfig } from "./api/settings";
import { type TestCase } from "./api/types";
import { CoveragePanel } from "./components/CoveragePanel";
import { GeneratePanel } from "./components/GeneratePanel";
import { HistoryPanel } from "./components/HistoryPanel";
import { JobsPanel } from "./components/JobsPanel";
import { KnowledgePanel } from "./components/KnowledgePanel";

type NavKey = "generate" | "jobs" | "knowledge" | "history" | "coverage";

const NAV_ITEMS: Array<{ key: NavKey; label: string; icon: LucideIcon }> = [
  { key: "generate", label: "生成", icon: WandSparkles },
  { key: "jobs", label: "任务", icon: ClipboardList },
  { key: "knowledge", label: "知识库", icon: Database },
  { key: "history", label: "历史", icon: History },
  { key: "coverage", label: "覆盖率", icon: BarChart3 }
];

function App() {
  const [activeNav, setActiveNav] = useState<NavKey>("generate");
  const [settings, setSettings] = useState<ApiConfig>(() => loadApiConfig());
  const [savedSettings, setSavedSettings] = useState<ApiConfig>(() => loadApiConfig());
  const [health, setHealth] = useState<{ label: string; ok: boolean | null }>({
    label: "未检查",
    ok: null
  });
  const [checkingHealth, setCheckingHealth] = useState(false);
  const [activeCases, setActiveCases] = useState<TestCase[]>([]);

  const api = useMemo(() => new ApiClient(savedSettings), [savedSettings]);

  const saveSettings = () => {
    const nextSettings = saveApiConfig(settings);
    setSettings(nextSettings);
    setSavedSettings(nextSettings);
  };

  const checkHealth = async () => {
    setCheckingHealth(true);
    try {
      const result = await new ApiClient(settings).health();
      setHealth({ label: `${result.service} 可用`, ok: true });
    } catch (error) {
      setHealth({ label: getErrorMessage(error), ok: false });
    } finally {
      setCheckingHealth(false);
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">
            <ShieldCheck size={22} aria-hidden="true" />
          </div>
          <div>
            <h1>测试用例生成</h1>
            <p>AI Test Case Generator</p>
          </div>
        </div>

        <nav className="nav-list" aria-label="主导航">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              className={activeNav === item.key ? "nav-item active" : "nav-item"}
              type="button"
              onClick={() => setActiveNav(item.key)}
            >
              <item.icon size={18} aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="connection-grid">
            <label>
              <span>API Base</span>
              <input
                value={settings.baseUrl}
                onChange={(event) =>
                  setSettings((current) => ({ ...current, baseUrl: event.target.value }))
                }
                spellCheck={false}
              />
            </label>
            <label>
              <span>API Key</span>
              <input
                type="password"
                value={settings.apiKey}
                onChange={(event) =>
                  setSettings((current) => ({ ...current, apiKey: event.target.value }))
                }
                spellCheck={false}
              />
            </label>
          </div>
          <div className="toolbar-actions">
            <button className="icon-button" type="button" onClick={saveSettings} title="保存连接配置">
              <Save size={18} aria-hidden="true" />
            </button>
            <button
              className="icon-button"
              type="button"
              onClick={checkHealth}
              title="检查服务健康状态"
              disabled={checkingHealth}
            >
              {checkingHealth ? (
                <Loader2 className="spin" size={18} aria-hidden="true" />
              ) : (
                <KeyRound size={18} aria-hidden="true" />
              )}
            </button>
            <span
              className={
                health.ok === null ? "connection-state" : health.ok ? "connection-state ok" : "connection-state bad"
              }
            >
              {health.ok === true && <CheckCircle2 size={16} aria-hidden="true" />}
              {health.ok === false && <XCircle size={16} aria-hidden="true" />}
              {health.label}
            </span>
          </div>
        </header>

        <div className="content">
          {activeNav === "generate" && (
            <GeneratePanel api={api} onCasesReady={setActiveCases} />
          )}
          {activeNav === "jobs" && (
            <JobsPanel api={api} onCasesReady={setActiveCases} />
          )}
          {activeNav === "knowledge" && <KnowledgePanel api={api} />}
          {activeNav === "history" && (
            <HistoryPanel
              api={api}
              onCasesReady={setActiveCases}
              onOpenCoverage={() => setActiveNav("coverage")}
            />
          )}
          {activeNav === "coverage" && (
            <CoveragePanel api={api} currentCases={activeCases} />
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
