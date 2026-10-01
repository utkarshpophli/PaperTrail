import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Visual } from "@/lib/story-api";
import { layoutArchitecture, wrapLabel } from "./architecture-layout";
import { barPercent } from "./comparison-visual";
import { VisualRenderer } from "./visual-renderer";

const frame = { eyebrow: "EYEBROW", caption: "CAPTION" };

const VISUALS: { name: string; visual: Visual; expected: string[] }[] = [
  { name: "metric", visual: { ...frame, type: "metric", items: [{ label: "BLEU", value: "28.4", note: "En-De" }] }, expected: ["BLEU", "28.4", "En-De"] },
  { name: "flow", visual: { ...frame, type: "flow", items: [{ label: "Encode", detail: "tokens in" }, { label: "Decode", detail: "tokens out" }] }, expected: ["Encode", "tokens in", "Decode"] },
  {
    name: "comparison",
    visual: { ...frame, type: "comparison", items: [{ label: "Base", value: 27, display_value: "27.3", highlight: false }, { label: "Big", value: 28, display_value: "28.4", highlight: true }] },
    expected: ["Base", "27.3", "Big", "28.4", "Highlighted"],
  },
  { name: "concept", visual: { ...frame, type: "concept", center: "Attention", items: [{ label: "Query", detail: "asks" }, { label: "Key", detail: "answers" }, { label: "Value", detail: "carries" }] }, expected: ["Attention", "Query", "Key", "Value"] },
  { name: "layers", visual: { ...frame, type: "layers", items: [{ label: "Top", detail: "d1", tone: "accent" }, { label: "Bottom", detail: "d2", tone: "ink" }] }, expected: ["Top", "Bottom", "Layer 2", "Layer 1"] },
  { name: "quote", visual: { ...frame, type: "quote", quote: "Attention is all you need", attribution: "Title, p. 1" }, expected: ["“Attention is all you need”", "— Title, p. 1"] },
  {
    name: "architecture",
    visual: {
      ...frame,
      type: "architecture",
      nodes: [
        { id: "a", label: "Embedding", detail: "maps tokens", group: "input" },
        { id: "b", label: "Encoder stack", detail: "six layers", group: "core" },
        { id: "c", label: "Softmax", detail: "probabilities", group: "output" },
        { id: "d", label: "Table 2", detail: "the BLEU table", group: "evidence" },
      ],
      edges: [{ source: "a", target: "b", label: "embeds" }, { source: "b", target: "c", label: "" }, { source: "b", target: "ghost", label: "x" }],
    },
    expected: ["Embedding", "Encoder stack", "Softmax", "Table 2", "Input", "Evidence"],
  },
  {
    name: "equation",
    visual: { ...frame, type: "equation", formula: "softmax(QK^T / sqrt(d_k))V", terms: [{ symbol: "Q", label: "queries", detail: "from decoder" }], steps: ["Score", "Scale"] },
    expected: ["softmax(QK^T / sqrt(d_k))V", "Q", "queries", "Score", "Scale"],
  },
  { name: "timeline", visual: { ...frame, type: "timeline", items: [{ label: "2014", detail: "seq2seq", tone: "paper" }, { label: "2017", detail: "transformer", tone: "accent" }] }, expected: ["2014", "2017", "transformer"] },
  {
    name: "matrix",
    visual: { ...frame, type: "matrix", columns: ["Speed", "Quality"], rows: [{ label: "RNN", cells: [{ label: "slow", tone: "low" }, { label: "good", tone: "medium" }] }] },
    expected: ["Speed", "Quality", "RNN", "slow", "good"],
  },
  { name: "infographic", visual: { ...frame, type: "infographic", items: [{ label: "Parallel", detail: "all positions", badge: "8 heads" }] }, expected: ["Parallel", "all positions", "8 heads"] },
];

describe("VisualRenderer", () => {
  it.each(VISUALS)("renders the $name grammar with eyebrow above and caption below", ({ visual, expected }) => {
    const { container } = render(<VisualRenderer visual={visual} />);
    for (const text of expected) expect(screen.getAllByText(text, { exact: true }).length, text).toBeGreaterThan(0);
    const figure = container.querySelector("figure");
    expect(figure?.firstElementChild).toHaveTextContent("EYEBROW");
    expect(figure?.lastElementChild).toHaveTextContent("CAPTION");
  });

  it("shows caption (and no crash) for an unknown visual type", () => {
    const unknown = { ...frame, type: "hologram" } as unknown as Visual;
    render(<VisualRenderer visual={unknown} />);
    expect(screen.getByText("CAPTION")).toBeInTheDocument();
  });

  it("renders hostile strings literally", () => {
    const hostile = "<script>alert(1)</script><img src=x onerror=alert(1)>";
    const visual: Visual = {
      ...frame,
      type: "infographic",
      items: [{ label: hostile, detail: hostile, badge: hostile }],
    };
    const { container } = render(<VisualRenderer visual={visual} />);
    expect(screen.getAllByText(hostile).length).toBe(3);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("renders hostile architecture and quote text literally", () => {
    const hostile = "<b>bold</b>";
    const arch: Visual = { ...frame, type: "architecture", nodes: [{ id: "a", label: hostile, detail: hostile, group: "core" }], edges: [] };
    const { container, unmount } = render(<VisualRenderer visual={arch} />);
    expect(container.querySelector("b")).toBeNull();
    unmount();
    render(<VisualRenderer visual={{ ...frame, type: "quote", quote: hostile, attribution: hostile }} />);
    expect(screen.getByText(`“${hostile}”`)).toBeInTheDocument();
  });

  it("marks the highlighted comparison bar and prints every value as text", () => {
    const { container } = render(<VisualRenderer visual={VISUALS[2].visual} />);
    const bars = container.querySelectorAll<HTMLElement>("[data-bar]");
    expect(bars[1].style.width).toBe("100%");
    expect(parseFloat(bars[0].style.width)).toBeLessThan(100);
  });

  it("architecture always lists components and connections as text, skipping dangling edges", () => {
    render(<VisualRenderer visual={VISUALS[6].visual} />);
    const connections = screen.getByRole("list", { name: "Connections" });
    expect(within(connections).getAllByRole("listitem")).toHaveLength(2);
    expect(connections).toHaveTextContent("Embedding → Encoder stack: embeds");
  });

  it("architecture with no nodes degrades without an svg", () => {
    const { container } = render(<VisualRenderer visual={{ ...frame, type: "architecture", nodes: [], edges: [] }} />);
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText("CAPTION")).toBeInTheDocument();
  });
});

describe("barPercent", () => {
  it("scales to max with a visible minimum", () => {
    expect(barPercent(50, 100)).toBe(50);
    expect(barPercent(0, 100)).toBe(4);
    expect(barPercent(-3, 100)).toBe(4);
    expect(barPercent(1, 1000)).toBe(4);
    expect(barPercent(5, 0)).toBe(4);
  });
});

describe("layoutArchitecture", () => {
  const node = (id: string, group: "input" | "core" | "output" | "evidence") => ({ id, label: id, detail: "", group });

  it("orders columns input -> core -> output -> evidence and drops unused groups", () => {
    const layout = layoutArchitecture([node("e", "evidence"), node("o", "output"), node("i", "input")], []);
    expect(layout?.columns.map((c) => c.group)).toEqual(["input", "output", "evidence"]);
    const xs = layout?.columns.map((c) => c.x) ?? [];
    expect([...xs].sort((a, b) => a - b)).toEqual(xs);
  });

  it("returns null for empty or oversized graphs", () => {
    expect(layoutArchitecture([], [])).toBeNull();
    expect(layoutArchitecture(Array.from({ length: 25 }, (_, i) => node(`n${i}`, "core")), [])).toBeNull();
  });

  it("skips self loops and dangling edges, keeps valid ones", () => {
    const layout = layoutArchitecture(
      [node("a", "input"), node("b", "core")],
      [{ source: "a", target: "a", label: "" }, { source: "a", target: "zzz", label: "" }, { source: "a", target: "b", label: "ok" }],
    );
    expect(layout?.edges.map((e) => e.edge.label)).toEqual(["ok"]);
  });

  it("wraps long labels into at most two lines", () => {
    expect(wrapLabel("Multi-Head Scaled Dot Product Attention Block Extra Words")).toHaveLength(2);
    expect(wrapLabel("Short")).toEqual(["Short"]);
  });
});
