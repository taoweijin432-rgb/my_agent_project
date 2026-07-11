import { BookOpen, Loader2, RefreshCw, Save, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { getErrorMessage, type ApiClient } from "../api/client";
import { splitTags } from "../api/requirements";
import type { KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentSummary } from "../api/types";
import { ChunkList, EmptyState, ErrorBanner, SuccessBanner, TagList } from "./common";

interface KnowledgePanelProps {
  api: ApiClient;
}

export function KnowledgePanel({ api }: KnowledgePanelProps) {
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [form, setForm] = useState<KnowledgeDocument>({
    source: "manual/login-prd.md",
    content: "",
    document_type: "prd",
    module: "login",
    tags: ["login"]
  });
  const [chunkSize, setChunkSize] = useState(900);
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([]);
  const [loading, setLoading] = useState<"list" | "save" | "query" | "delete" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    setLoading("list");
    setError(null);
    try {
      const response = await api.listKnowledgeDocuments({ limit: 100, offset: 0 });
      setDocuments(response.documents);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  }, [api]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  const updateForm = <K extends keyof KnowledgeDocument>(key: K, value: KnowledgeDocument[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const saveDocument = async (event: FormEvent) => {
    event.preventDefault();
    setLoading("save");
    setError(null);
    setMessage(null);
    try {
      const response = await api.upsertKnowledgeDocument(form, chunkSize);
      setMessage(
        `${response.source} v${response.version} 已更新，新增 ${response.added_chunks} 个分块，替换 ${response.replaced_chunks} 个分块。`
      );
      await loadDocuments();
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const deleteDocument = async (source: string) => {
    if (!window.confirm(`删除知识文档：${source}`)) {
      return;
    }
    setLoading("delete");
    setError(null);
    setMessage(null);
    try {
      const response = await api.deleteKnowledgeDocument(source);
      setMessage(`${response.source} 已删除 ${response.deleted_chunks} 个分块。`);
      await loadDocuments();
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  const searchKnowledge = async (event: FormEvent) => {
    event.preventDefault();
    setLoading("query");
    setError(null);
    try {
      const response = await api.queryKnowledge(query, topK);
      setChunks(response.chunks);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(null);
    }
  };

  return (
    <section className="page-grid knowledge-grid">
      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>知识文档</h2>
            <p>按 source 更新和删除文档。</p>
          </div>
          <button className="icon-button" type="button" onClick={loadDocuments} title="刷新文档列表">
            {loading === "list" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <RefreshCw size={18} aria-hidden="true" />
            )}
          </button>
        </div>

        {error && <ErrorBanner message={error} />}
        {message && <SuccessBanner message={message} />}

        <div className="document-list">
          {documents.map((document) => (
            <div key={document.source} className="document-row">
              <div>
                <strong>{document.source}</strong>
                <p>
                  {document.module} · {document.document_type} · v{document.version} ·{" "}
                  {document.chunk_count} chunks
                </p>
                <TagList tags={document.tags} />
              </div>
              <button
                className="icon-button danger"
                type="button"
                title="删除文档"
                disabled={loading === "delete"}
                onClick={() => void deleteDocument(document.source)}
              >
                <Trash2 size={18} aria-hidden="true" />
              </button>
            </div>
          ))}
          {documents.length === 0 && <EmptyState icon={BookOpen} title="暂无知识文档" />}
        </div>
      </div>

      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>更新文档</h2>
            <p>写入后立即进入 RAG 检索库。</p>
          </div>
        </div>
        <form className="stack-form" onSubmit={saveDocument}>
          <label>
            <span>Source</span>
            <input
              value={form.source}
              onChange={(event) => updateForm("source", event.target.value)}
              required
            />
          </label>
          <div className="form-row">
            <label>
              <span>类型</span>
              <input
                value={form.document_type}
                onChange={(event) => updateForm("document_type", event.target.value)}
              />
            </label>
            <label>
              <span>模块</span>
              <input value={form.module} onChange={(event) => updateForm("module", event.target.value)} />
            </label>
            <label>
              <span>分块大小</span>
              <input
                type="number"
                min={200}
                max={3000}
                value={chunkSize}
                onChange={(event) => setChunkSize(Number(event.target.value))}
              />
            </label>
          </div>
          <label>
            <span>标签</span>
            <input
              value={form.tags.join(", ")}
              onChange={(event) => updateForm("tags", splitTags(event.target.value))}
            />
          </label>
          <label className="field-block">
            <span>内容</span>
            <textarea
              className="document-input"
              value={form.content}
              onChange={(event) => updateForm("content", event.target.value)}
              required
            />
          </label>
          <button className="primary-button" type="submit" disabled={loading === "save"}>
            {loading === "save" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <Save size={18} aria-hidden="true" />
            )}
            <span>保存文档</span>
          </button>
        </form>
      </div>

      <div className="panel query-panel">
        <div className="panel-heading">
          <div>
            <h2>检索验证</h2>
            <p>返回当前知识库匹配片段。</p>
          </div>
        </div>
        <form className="query-form" onSubmit={searchKnowledge}>
          <input value={query} onChange={(event) => setQuery(event.target.value)} required />
          <input
            type="number"
            min={1}
            max={10}
            value={topK}
            onChange={(event) => setTopK(Number(event.target.value))}
          />
          <button className="primary-button" type="submit" disabled={loading === "query"}>
            {loading === "query" ? (
              <Loader2 className="spin" size={18} aria-hidden="true" />
            ) : (
              <Search size={18} aria-hidden="true" />
            )}
            <span>检索</span>
          </button>
        </form>
        <ChunkList chunks={chunks} />
      </div>
    </section>
  );
}
