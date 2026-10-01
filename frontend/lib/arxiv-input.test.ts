import { describe, expect, it } from "vitest";
import { extractArxivId, toPaperSource } from "./arxiv-input";

describe("extractArxivId", () => {
  it.each([
    ["1706.03762", "1706.03762"],
    ["  1706.03762v5 ", "1706.03762v5"],
    ["arXiv:1706.03762", "1706.03762"],
    ["https://arxiv.org/abs/1706.03762", "1706.03762"],
    ["https://arxiv.org/abs/1706.03762v7", "1706.03762v7"],
    ["https://arxiv.org/pdf/1706.03762", "1706.03762"],
    ["https://arxiv.org/pdf/1706.03762.pdf", "1706.03762"],
    ["https://arxiv.org/pdf/1706.03762v7.pdf", "1706.03762v7"],
    ["http://export.arxiv.org/abs/2405.01234", "2405.01234"],
    ["arxiv.org/abs/2405.01234", "2405.01234"],
    ["https://arxiv.org/abs/hep-th/9901001", "hep-th/9901001"],
  ])("extracts the id from %s", (input, expected) => {
    expect(extractArxivId(input)).toBe(expected);
  });

  it.each(["Attention Is All You Need", "https://example.com/abs/1706.03762", "https://arxiv.org/list/cs.AI/recent", ""])(
    "returns null for %s",
    (input) => {
      expect(extractArxivId(input)).toBeNull();
    },
  );
});

describe("toPaperSource", () => {
  it("prefers a file, then an arXiv id, then a title", () => {
    const file = new File(["x"], "p.pdf", { type: "application/pdf" });
    expect(toPaperSource(file, "1706.03762")).toEqual({ kind: "file", file });
    expect(toPaperSource(null, "https://arxiv.org/pdf/1706.03762")).toEqual({ kind: "arxiv", arxivId: "1706.03762" });
    expect(toPaperSource(null, "Attention Is All You Need")).toEqual({ kind: "title", title: "Attention Is All You Need" });
    expect(toPaperSource(null, "   ")).toBeNull();
  });
});
