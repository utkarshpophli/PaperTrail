import { describe, expect, it } from "vitest";
import { computeEvidenceHealth, type CitingSection } from "./evidence-health";
import { makeClaim } from "./studio-fixtures";

const section = (id: string, source: CitingSection["source"], claimIds: string[]): CitingSection => ({
  id,
  title: id,
  source,
  claimIds,
});

describe("computeEvidenceHealth", () => {
  it("handles no claims and no sections", () => {
    const h = computeEvidenceHealth([], []);
    expect(h).toMatchObject({ totalClaims: 0, verifiedClaims: 0, citedPages: [], pageGaps: [], pageSpan: 0, unusedClaims: [] });
    expect(h.thinSections).toEqual([]);
  });

  it("counts verified over total", () => {
    const h = computeEvidenceHealth(
      [makeClaim("a"), makeClaim("b", { status: "mismatch" }), makeClaim("c", { status: "needs-review" })],
      [],
    );
    expect([h.verifiedClaims, h.totalClaims]).toEqual([1, 3]);
  });

  it("finds distinct cited pages and gaps between first and last only", () => {
    const h = computeEvidenceHealth([makeClaim("a", { pages: [2, 3] }), makeClaim("b", { pages: [3, 6] })], []);
    expect(h.citedPages).toEqual([2, 3, 6]);
    expect(h.pageGaps).toEqual([4, 5]);
    expect(h.pageSpan).toBe(5);
  });

  it("reports a single cited page with no gaps", () => {
    const h = computeEvidenceHealth([makeClaim("a", { pages: [4] })], []);
    expect(h.pageGaps).toEqual([]);
    expect(h.pageSpan).toBe(1);
  });

  it("treats every claim as unused when no section cites any", () => {
    const h = computeEvidenceHealth([makeClaim("a"), makeClaim("b")], [section("s", "story", [])]);
    expect(h.usedClaims).toEqual([]);
    expect(h.unusedClaims.map((c) => c.id)).toEqual(["a", "b"]);
  });

  it("counts story, report, technical and learning citations as use; ignores unknown ids", () => {
    const h = computeEvidenceHealth(
      [makeClaim("a"), makeClaim("b"), makeClaim("c"), makeClaim("d"), makeClaim("e")],
      [
        section("s", "story", ["a", "ghost"]),
        section("r", "report", ["b"]),
        section("t", "technical", ["c"]),
        section("l", "learning", ["d"]),
      ],
    );
    expect(h.usedClaims.map((c) => c.id)).toEqual(["a", "b", "c", "d"]);
    expect(h.unusedClaims.map((c) => c.id)).toEqual(["e"]);
  });

  it("flags thin story/report sections: none, single claim, none verified", () => {
    const claims = [makeClaim("a"), makeClaim("b"), makeClaim("x", { status: "not-found" }), makeClaim("y", { status: "mismatch" })];
    const h = computeEvidenceHealth(claims, [
      section("empty", "story", []),
      section("single", "report", ["a"]),
      section("unverified", "story", ["x", "y"]),
      section("fine", "story", ["a", "b"]),
      section("tech-single", "technical", ["a"]),
    ]);
    expect(h.thinSections.map((t) => [t.section.id, t.reason])).toEqual([
      ["empty", "no-claims"],
      ["single", "single-claim"],
      ["unverified", "no-verified"],
    ]);
  });

  it("does not double count a repeated claim id", () => {
    const h = computeEvidenceHealth([makeClaim("a"), makeClaim("b")], [section("dup", "story", ["a", "a"])]);
    expect(h.thinSections[0]).toMatchObject({ reason: "single-claim", claimCount: 1 });
  });
});
