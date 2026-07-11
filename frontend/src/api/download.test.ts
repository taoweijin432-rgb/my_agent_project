import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadBlob } from "./download";

describe("downloadBlob", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a temporary object url and clicks a download anchor", () => {
    const blob = new Blob(["content"], { type: "text/plain" });
    const createObjectURL = vi.fn().mockReturnValue("blob:test-url");
    const revokeObjectURL = vi.fn();
    const anchor = document.createElement("a");
    const click = vi.spyOn(anchor, "click").mockImplementation(() => undefined);
    const remove = vi.spyOn(anchor, "remove").mockImplementation(() => undefined);
    const createElement = vi
      .spyOn(document, "createElement")
      .mockReturnValue(anchor);

    downloadBlob(blob, "generated.py", {
      document,
      createObjectURL,
      revokeObjectURL
    });

    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(createElement).toHaveBeenCalledWith("a");
    expect(anchor.href).toBe("blob:test-url");
    expect(anchor.download).toBe("generated.py");
    expect(click).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test-url");
  });
});
