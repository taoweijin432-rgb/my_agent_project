import { AlertCircle, BookOpen, CheckCircle2, Loader2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { getStatusLabel } from "../api/format";
import type { KnowledgeChunk } from "../api/types";

export function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge status-${status}`}>{getStatusLabel(status)}</span>;
}

export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function EmptyState({ icon: Icon, title }: { icon: LucideIcon; title: string }) {
  return (
    <div className="empty-state">
      <Icon size={30} aria-hidden="true" />
      <span>{title}</span>
    </div>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="empty-state">
      <Loader2 className="spin" size={30} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="banner error-banner">
      <AlertCircle size={18} aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

export function SuccessBanner({ message }: { message: string }) {
  return (
    <div className="banner success-banner">
      <CheckCircle2 size={18} aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

export function TextList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="text-list">
      <strong>{title}</strong>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function OrderedInlineList({ items }: { items: string[] }) {
  return (
    <ol className="inline-list">
      {items.map((item, index) => (
        <li key={`${index}-${item}`}>{item}</li>
      ))}
    </ol>
  );
}

export function TagList({ tags }: { tags: string[] }) {
  const filteredTags = Array.from(new Set(tags.filter(Boolean)));
  if (filteredTags.length === 0) {
    return null;
  }
  return (
    <div className="tag-list">
      {filteredTags.map((tag) => (
        <span key={tag}>{tag}</span>
      ))}
    </div>
  );
}

export function ChunkList({ chunks }: { chunks: KnowledgeChunk[] }) {
  if (chunks.length === 0) {
    return <EmptyState icon={BookOpen} title="暂无片段" />;
  }

  return (
    <div className="chunk-list">
      {chunks.map((chunk, index) => (
        <article key={`${chunk.source}-${chunk.chunk ?? index}`} className="chunk-row">
          <header>
            <strong>{chunk.source}</strong>
            <span>{chunk.score === null ? "-" : chunk.score.toFixed(3)}</span>
          </header>
          <p>{chunk.content}</p>
          <TagList tags={[chunk.module, chunk.document_type, ...chunk.tags].filter(Boolean) as string[]} />
        </article>
      ))}
    </div>
  );
}
