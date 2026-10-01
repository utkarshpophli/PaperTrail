import { describe, expect, it } from "vitest";
import { placeFigures } from "./figure-placement";
import { makeFigure } from "./studio-fixtures";

const sections = [
  { id: "s1", claim_ids: ["a", "b"] },
  { id: "s2", claim_ids: ["b", "c"] },
];

describe("placeFigures", () => {
  it("places a figure in the first section whose claims intersect", () => {
    const { bySection, unplaced } = placeFigures(sections, [makeFigure("f1", ["b"]), makeFigure("f2", ["c"])]);
    expect(bySection.get("s1")?.map((f) => f.id)).toEqual(["f1"]);
    expect(bySection.get("s2")?.map((f) => f.id)).toEqual(["f2"]);
    expect(unplaced).toEqual([]);
  });

  it("places each figure at most once even when several sections match", () => {
    const { bySection } = placeFigures(sections, [makeFigure("f1", ["a", "b", "c"])]);
    const all = [...bySection.values()].flat();
    expect(all).toHaveLength(1);
    expect(bySection.has("s2")).toBe(false);
  });

  it("returns figures with no matching claims (or none at all) as unplaced, in order", () => {
    const { unplaced } = placeFigures(sections, [makeFigure("f1", ["zzz"]), makeFigure("f2", []), makeFigure("f3", ["a"])]);
    expect(unplaced.map((f) => f.id)).toEqual(["f1", "f2"]);
  });

  it("prefers the section whose text names the figure over an earlier claim match", () => {
    const withText = [
      { id: "s1", claim_ids: ["a"], text: "Overview of the results." },
      { id: "s2", claim_ids: [], text: "The architecture (Figure 2) routes tokens to experts." },
    ];
    const figure = { ...makeFigure("f1", ["a"]), label: "Figure 2" };
    const { bySection } = placeFigures(withText, [figure]);
    expect(bySection.get("s2")?.map((f) => f.id)).toEqual(["f1"]);
  });

  it("matches a label as a whole number, so Figure 2 is not placed by a mention of Figure 21", () => {
    const withText = [{ id: "s1", claim_ids: [], text: "See Figure 21 and Table 3." }];
    const { bySection, unplaced } = placeFigures(withText, [
      { ...makeFigure("f2", []), label: "Figure 2" },
      { ...makeFigure("t3", []), label: "Table 3" },
    ]);
    expect(bySection.get("s1")?.map((f) => f.id)).toEqual(["t3"]);
    expect(unplaced.map((f) => f.id)).toEqual(["f2"]);
  });

  it("handles no sections", () => {
    const { bySection, unplaced } = placeFigures([], [makeFigure("f1", ["a"])]);
    expect(bySection.size).toBe(0);
    expect(unplaced).toHaveLength(1);
  });
});
