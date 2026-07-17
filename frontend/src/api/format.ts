import { TEST_CASE_TYPE_OPTIONS, type TestCaseType } from "./types";

export function getTypeLabel(type: TestCaseType): string {
  return TEST_CASE_TYPE_OPTIONS.find((option) => option.value === type)?.label || type;
}

export function getStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "排队",
    running: "运行中",
    succeeded: "成功",
    success: "成功",
    passed: "通过",
    failed: "失败",
    blocked: "阻塞",
    skipped: "跳过",
    incomplete: "未完成",
    pending: "待处理",
    approved: "已批准",
    rejected: "已驳回"
  };
  return labels[status] || status;
}

export function formatDate(value: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function formatDuration(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  return value < 1000 ? `${value.toFixed(0)} ms` : `${(value / 1000).toFixed(1)} s`;
}

export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  return `${Math.round(value * 100)}%`;
}
