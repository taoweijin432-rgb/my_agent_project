import { describe, expect, it } from "vitest";

import {
  formatDate,
  formatDuration,
  formatPercent,
  getStatusLabel,
  getTypeLabel
} from "./format";

describe("format helpers", () => {
  it("formats dates and keeps empty or invalid values readable", () => {
    expect(formatDate(null)).toBe("-");
    expect(formatDate("not-a-date")).toBe("not-a-date");
    expect(formatDate("2026-07-08T12:34:56")).toMatch(/2026.*7.*8.*12.*34/);
  });

  it("formats durations", () => {
    expect(formatDuration(250)).toBe("250 ms");
    expect(formatDuration(1500)).toBe("1.5 s");
    expect(formatDuration(Number.POSITIVE_INFINITY)).toBe("-");
  });

  it("formats percentages", () => {
    expect(formatPercent(0.876)).toBe("88%");
    expect(formatPercent(Number.NaN)).toBe("-");
  });

  it("maps known status and type labels while preserving unknown statuses", () => {
    expect(getStatusLabel("queued")).toBe("排队");
    expect(getStatusLabel("custom")).toBe("custom");
    expect(getTypeLabel("security")).toBe("安全");
  });
});
