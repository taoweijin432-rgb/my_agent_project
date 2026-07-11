import { describe, expect, it } from "vitest";

import { parseRequirements, splitTags } from "./requirements";

describe("splitTags", () => {
  it("splits tags by English comma, Chinese comma, and new lines", () => {
    expect(splitTags("手机号, 验证码，登录成功\n风控,,")).toEqual([
      "手机号",
      "验证码",
      "登录成功",
      "风控"
    ]);
  });
});

describe("parseRequirements", () => {
  it("parses requirement lines in id-title-keywords-priority format", () => {
    expect(
      parseRequirements("REQ-001 | 登录成功 | 手机号, 验证码 | critical")
    ).toEqual([
      {
        id: "REQ-001",
        title: "登录成功",
        description: "登录成功",
        keywords: ["手机号", "验证码"],
        priority: "critical",
        source: "frontend"
      }
    ]);
  });

  it("fills defaults and falls back to medium priority for invalid values", () => {
    expect(parseRequirements(" | 验证码过期 | 过期，提示 | urgent\nREQ-003")).toEqual([
      {
        id: "REQ-001",
        title: "验证码过期",
        description: "验证码过期",
        keywords: ["过期", "提示"],
        priority: "medium",
        source: "frontend"
      },
      {
        id: "REQ-003",
        title: "REQ-003",
        description: "REQ-003",
        keywords: ["REQ-003"],
        priority: "medium",
        source: "frontend"
      }
    ]);
  });

  it("ignores blank lines", () => {
    expect(parseRequirements("\n\nREQ-001 | 登录成功\n\n")).toHaveLength(1);
  });
});
