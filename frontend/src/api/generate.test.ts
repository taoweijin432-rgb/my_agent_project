import { describe, expect, it } from "vitest";

import { normalizeGenerateRequest } from "./generate";
import type { GenerateRequest } from "./types";

const BASE_REQUEST: GenerateRequest = {
  description: "生成登录接口测试用例",
  max_cases: 8,
  knowledge_top_k: 5,
  include_context: true,
  focus_types: ["functional", "security"]
};

describe("normalizeGenerateRequest", () => {
  it("trims descriptions and preserves valid request fields", () => {
    expect(
      normalizeGenerateRequest({
        ...BASE_REQUEST,
        description: "  生成登录接口测试用例  "
      })
    ).toEqual(BASE_REQUEST);
  });

  it("clamps numeric fields to backend-supported ranges", () => {
    expect(
      normalizeGenerateRequest({
        ...BASE_REQUEST,
        max_cases: 100,
        knowledge_top_k: -5
      })
    ).toMatchObject({
      max_cases: 50,
      knowledge_top_k: 0
    });
  });

  it("uses minimum values for NaN fields", () => {
    expect(
      normalizeGenerateRequest({
        ...BASE_REQUEST,
        max_cases: Number.NaN,
        knowledge_top_k: Number.NaN
      })
    ).toMatchObject({
      max_cases: 1,
      knowledge_top_k: 0
    });
  });

  it("normalizes empty focus type arrays to null", () => {
    expect(
      normalizeGenerateRequest({
        ...BASE_REQUEST,
        focus_types: []
      }).focus_types
    ).toBeNull();
  });
});
