import { describe, expect, it } from "vitest";
import { parseFigures, parseStorySpec } from "./story-api";

const section = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: "s1",
  index_label: "01",
  kicker: "k",
  title: "T",
  body: "b",
  claim_ids: ["c1"],
  visual: { type: "flow", eyebrow: "e", caption: "c", items: [{ label: "a", detail: "d" }] },
  ...over,
});

describe("parseStorySpec", () => {
  it("parses meta and sections", () => {
    const spec = parseStorySpec({
      meta: { title: "t", dek: "d", reading_time: "5 min", closing: { title: "x", body: "y" } },
      sections: [section()],
    });
    expect(spec?.meta.closing).toEqual({ title: "x", body: "y" });
    expect(spec?.sections[0].visual).toMatchObject({ type: "flow", items: [{ label: "a", detail: "d" }] });
  });

  it("returns null for non-objects and missing meta", () => {
    expect(parseStorySpec(null)).toBeNull();
    expect(parseStorySpec({ sections: [] })).toBeNull();
  });

  it("drops malformed sections and malformed items instead of throwing", () => {
    const spec = parseStorySpec({
      meta: { title: "t" },
      sections: [
        section({ id: null }),
        "junk",
        section({ id: "ok", visual: { type: "metric", eyebrow: "", caption: "", items: [{ label: "L", value: 3 }, 7, {}] } }),
      ],
    });
    expect(spec?.sections.map((s) => s.id)).toEqual(["ok"]);
    expect(spec?.sections[0].visual).toMatchObject({ items: [{ label: "L", value: "3", note: "" }] });
  });

  it("degrades an unknown visual type to unsupported and a non-object visual to null", () => {
    const spec = parseStorySpec({
      meta: {},
      sections: [
        section({ id: "a", visual: { type: "hologram", eyebrow: "E", caption: "C" } }),
        section({ id: "b", visual: "nope" }),
      ],
    });
    expect(spec?.sections[0].visual).toEqual({ type: "unsupported", rawType: "hologram", eyebrow: "E", caption: "C" });
    expect(spec?.sections[1].visual).toBeNull();
  });

  it("normalises tones and non-finite comparison values", () => {
    const spec = parseStorySpec({
      meta: {},
      sections: [
        section({
          visual: {
            type: "comparison",
            items: [
              { label: "a", value: 1, display_value: "1x", highlight: true },
              { label: "b", value: "9" },
            ],
          },
        }),
        section({ id: "s2", visual: { type: "layers", items: [{ label: "x", tone: "neon" }] } }),
      ],
    });
    expect(spec?.sections[0].visual).toMatchObject({ items: [{ label: "a", highlight: true }] });
    expect((spec?.sections[0].visual as { items: unknown[] }).items).toHaveLength(1);
    expect(spec?.sections[1].visual).toMatchObject({ items: [{ tone: "paper" }] });
  });
});

describe("parseFigures", () => {
  it("parses valid figures and drops malformed ones", () => {
    const figures = parseFigures([
      { id: "f.png", filename: "f.png", page: 3, label: "Figure 3", caption: "cap", why_it_matters: " ", claim_ids: ["a", 1] },
      { filename: "g.png" },
      null,
    ]);
    expect(figures).toEqual([
      { id: "f.png", filename: "f.png", page: 3, label: "Figure 3", caption: "cap", why_it_matters: null, claim_ids: ["a"] },
    ]);
  });

  it("returns [] for non-arrays", () => {
    expect(parseFigures({})).toEqual([]);
  });
});
