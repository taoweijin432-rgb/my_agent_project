import { beforeEach, describe, expect, it } from "vitest";

import { DEFAULT_API_CONFIG, loadApiConfig, saveApiConfig } from "./settings";

describe("api settings storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns defaults when no stored settings exist", () => {
    expect(loadApiConfig()).toEqual(DEFAULT_API_CONFIG);
  });

  it("trims and persists api settings", () => {
    const saved = saveApiConfig({
      baseUrl: " /api/v1 ",
      apiKey: " test-key "
    });

    expect(saved).toEqual({
      baseUrl: "/api/v1",
      apiKey: "test-key"
    });
    expect(loadApiConfig()).toEqual(saved);
  });

  it("falls back to default base url when saved base url is blank", () => {
    expect(saveApiConfig({ baseUrl: " ", apiKey: "" })).toEqual(DEFAULT_API_CONFIG);
  });

  it("ignores malformed stored settings", () => {
    localStorage.setItem("ai-testcase-generator.frontend.settings", "{bad json");

    expect(loadApiConfig()).toEqual(DEFAULT_API_CONFIG);
  });
});
