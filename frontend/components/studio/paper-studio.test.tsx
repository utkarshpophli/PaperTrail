import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "@/lib/api-client";
import type { PaperResponse } from "@/lib/paper-types";
import { STORY_SPEC_FIXTURE, makeClaim, makeEvidence, makeFigure } from "@/lib/studio-fixtures";
import { PaperStudio } from "./paper-studio";

const api = vi.hoisted(() => ({
  getPaper: vi.fn(),
  getPaperPage: vi.fn(),
  getEvidence: vi.fn(),
  getReport: vi.fn(),
  getStory: vi.fn(),
  getTechnicalAppendix: vi.fn(),
  getLearning: vi.fn(),
  getStorySpec: vi.fn(),
  getFigures: vi.fn(),
}));

vi.mock("@/lib/papers-api", () => ({
  getPaper: api.getPaper,
  getPaperPage: api.getPaperPage,
  figureUrl: (id: string, file: string) => `http://api.test/papers/${id}/figures/${file}`,
}));
vi.mock("@/lib/evidence-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/evidence-api")>()),
  getEvidence: api.getEvidence,
  getReport: api.getReport,
  getStory: api.getStory,
  getTechnicalAppendix: api.getTechnicalAppendix,
  getLearning: api.getLearning,
}));
vi.mock("@/lib/story-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/story-api")>()),
  getStorySpec: api.getStorySpec,
  getFigures: api.getFigures,
}));

vi.mock("@/app/(app)/papers/[id]/analyze-panel", () => ({ AnalyzePanel: () => <div>mock-analyze-panel</div> }));
vi.mock("@/app/(app)/papers/[id]/assistant-panel", () => ({ AssistantPanel: () => <div>mock-assistant-panel</div> }));
vi.mock("@/app/(app)/papers/[id]/citations-panel", () => ({ CitationsPanel: () => <div>mock-citations-panel</div> }));
vi.mock("@/app/(app)/papers/[id]/learning-panel", () => ({ LearningPanel: () => <div>mock-learning-panel</div> }));
vi.mock("@/app/(app)/papers/[id]/generated-sections-panel", () => ({
  GeneratedSectionsPanel: ({ title }: { title: string }) => <div>mock-sections-{title}</div>,
}));
vi.mock("@/app/(app)/papers/[id]/repository-panel", () => ({ RepositoryPanel: () => <div>mock-repository-panel</div> }));
vi.mock("@/app/(app)/papers/[id]/code-links-panel", () => ({ CodeLinksPanel: () => <div>mock-code-links-panel</div> }));
vi.mock("@/app/(app)/papers/[id]/implementation-plan-panel", () => ({
  ImplementationPlanPanel: () => <div>mock-implementation-plan-panel</div>,
}));
vi.mock("@/app/(app)/papers/[id]/opencode-handoff-panel", () => ({
  OpencodeHandoffPanel: () => <div>mock-opencode-handoff-panel</div>,
}));

const PAPER: PaperResponse = {
  id: "paper-1",
  title: "Attention Is All You Need",
  authors: ["A. Vaswani"],
  year: 2017,
  venue: "NeurIPS",
  doi: null,
  arxiv_id: null,
  parse_status: "parsed",
  parse_error: null,
  created_at: "2024-01-01T00:00:00Z",
};

const CLAIMS = [
  makeClaim("c1", { kind: "method", statement: "Uses stacked attention", pages: [2] }),
  makeClaim("c2", { statement: "Reaches 28.4 BLEU", pages: [3] }),
  makeClaim("c3", { statement: "Trains faster", pages: [5], status: "mismatch" }),
  makeClaim("c4", { kind: "limitation", statement: "Quadratic memory", pages: [9] }),
];

function notFound(code: string): Promise<never> {
  return Promise.reject(new ApiRequestError(404, { code, message: code }));
}

interface Setup {
  paper?: PaperResponse;
  evidence?: "missing" | "ready";
  spec?: "typed" | "missing";
  plain?: boolean;
  figures?: ReturnType<typeof makeFigure>[];
}

function setup({ paper = PAPER, evidence = "ready", spec = "typed", plain = false, figures = [] }: Setup = {}) {
  api.getPaper.mockResolvedValue(paper);
  api.getEvidence.mockImplementation(() => (evidence === "ready" ? Promise.resolve(makeEvidence(CLAIMS)) : notFound("evidence_not_found")));
  api.getStorySpec.mockImplementation(() => (spec === "typed" ? Promise.resolve(STORY_SPEC_FIXTURE) : notFound("story_not_found")));
  api.getStory.mockImplementation(() =>
    plain
      ? Promise.resolve([{ id: "p1", title: "Plain heading", content: "Plain body text.", order: 1, claim_ids: ["c2"], created_at: "" }])
      : notFound("story_not_found"),
  );
  api.getFigures.mockResolvedValue(figures);
  api.getReport.mockImplementation(() => notFound("report_not_found"));
  api.getTechnicalAppendix.mockImplementation(() => notFound("technical_appendix_not_found"));
  api.getLearning.mockImplementation(() => notFound("learning_not_found"));
  api.getPaperPage.mockResolvedValue({ page_number: 1, text: "Raw page one text", figures: [] });
}

async function renderStudio(options?: Setup) {
  setup(options);
  render(<PaperStudio paperId="paper-1" />);
  await screen.findByRole("tablist", { name: "Studio mode" });
}

const tab = (name: string) => screen.getByRole("tab", { name });

let observerCallback: ((entries: unknown[]) => void) | null = null;

beforeEach(() => {
  observerCallback = null;
  class FakeObserver {
    constructor(callback: (entries: unknown[]) => void) {
      observerCallback = callback;
    }
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  vi.stubGlobal("IntersectionObserver", FakeObserver);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("PaperStudio shell", () => {
  it("shows the paper title, tabs and actions", async () => {
    await renderStudio();
    expect(await screen.findByText("Attention Is All You Need", { selector: "p" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Lab", "Story", "Preview"]);
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute("href", "/library");
    expect(screen.getByRole("link", { name: "+ New" })).toBeInTheDocument();
  });

  it("switches modes by click and with arrow keys, keeping roving tabindex", async () => {
    await renderStudio();
    expect(tab("Lab")).toHaveAttribute("aria-selected", "true");
    fireEvent.click(tab("Story"));
    expect(tab("Story")).toHaveAttribute("aria-selected", "true");
    expect(tab("Lab")).toHaveAttribute("tabindex", "-1");
    expect(await screen.findByText("Attention, unrolled")).toBeInTheDocument();
    fireEvent.keyDown(tab("Story"), { key: "ArrowRight" });
    expect(tab("Preview")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tab("Preview"), { key: "ArrowLeft" });
    fireEvent.keyDown(tab("Story"), { key: "ArrowLeft" });
    expect(tab("Lab")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "studio-tab-lab");
  });

  it("shows the parse error for a failed paper and does not offer the studio body", async () => {
    setup({ paper: { ...PAPER, parse_status: "failed", parse_error: "Corrupt PDF xref" } });
    render(<PaperStudio paperId="paper-1" />);
    expect(await screen.findByRole("status")).toHaveTextContent("Failed: Corrupt PDF xref");
    expect(screen.queryByRole("navigation", { name: "Paper map" })).toBeNull();
  });

  it("surfaces a paper load failure", async () => {
    setup();
    api.getPaper.mockRejectedValue(new Error("network down"));
    render(<PaperStudio paperId="paper-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("network down");
  });
});

describe("Lab", () => {
  it("shows the overview with thesis, question and numbered findings that open the drawer", async () => {
    await renderStudio();
    expect(await screen.findByText("Attention is enough.")).toBeInTheDocument();
    expect(screen.getByText("Can we drop recurrence?")).toBeInTheDocument();
    const findings = within(screen.getByRole("list", { name: "Key findings" }));
    fireEvent.click(findings.getByRole("button", { name: /Reaches 28.4 BLEU/ }));
    const drawer = screen.getByRole("complementary", { name: "Evidence" });
    expect(within(drawer).getByRole("heading", { name: "Reaches 28.4 BLEU" })).toBeInTheDocument();
    expect(within(drawer).getByText("Quote for c2 on page 3")).toBeInTheDocument();
  });

  it("shows the empty drawer text before any selection", async () => {
    await renderStudio();
    await screen.findByText("Attention is enough.");
    expect(screen.getByText(/Click a finding, or a source tag inside the story/)).toBeInTheDocument();
  });

  it("lists nav items and the claims ledger with N/M verified, row anchors and permalinks", async () => {
    await renderStudio();
    await screen.findByText("Attention is enough.");
    const nav = within(screen.getByRole("navigation", { name: "Paper map" }));
    for (const label of ["Overview", "Primer", "Learn & Try", "Deep report", "Technical", "Claims", "Evidence health", "Method", "Metrics", "Limitations", "Glossary", "Citations", "Ask", "Pages", "Re-analyze"]) {
      expect(nav.getByRole("button", { name: label })).toBeInTheDocument();
    }
    fireEvent.click(nav.getByRole("button", { name: "Claims" }));
    expect(screen.getByText("3/4 verified")).toBeInTheDocument();
    expect(document.getElementById("claim-c3")).not.toBeNull();
    expect(screen.getAllByRole("link", { name: /Permalink to claim/ })[0]).toHaveAttribute("href", "#claim-c1");
    const row = within(document.getElementById("claim-c3") as HTMLElement);
    expect(row.getByText("Mismatch")).toBeInTheDocument();
    expect(row.getByText("p. 5")).toBeInTheDocument();
    fireEvent.click(row.getByRole("button", { name: /Trains faster/ }));
    expect(within(screen.getByRole("complementary", { name: "Evidence" })).getByRole("status")).toHaveTextContent("Mismatch");
  });

  it("opens the first claim on a metric's page", async () => {
    await renderStudio();
    await screen.findByText("Attention is enough.");
    fireEvent.click(within(screen.getByRole("navigation", { name: "Paper map" })).getByRole("button", { name: "Metrics" }));
    expect(screen.getByText("Page 8")).toBeInTheDocument();
    // No claim cites page 8 in the fixture: the card is disabled rather than opening nothing.
    expect(screen.getByRole("button", { name: /BLEU/ })).toBeDisabled();
  });

  it("renders evidence health computed client-side", async () => {
    await renderStudio();
    await screen.findByText("Attention is enough.");
    fireEvent.click(within(screen.getByRole("navigation", { name: "Paper map" })).getByRole("button", { name: "Evidence health" }));
    expect(screen.getAllByText("3 / 4")).toHaveLength(2);
    expect(screen.getByText(/Uncited pages between 2 and 9: 4, 6, 7, 8/)).toBeInTheDocument();
    const unused = within(screen.getByRole("list", { name: "Unused claims" }));
    fireEvent.click(unused.getByRole("button", { name: "Quadratic memory" }));
    expect(within(screen.getByRole("complementary", { name: "Evidence" })).getByText("Quote for c4 on page 9")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Thin sections" })).toHaveTextContent("Story · 02 Attention only");
  });

  it("shows unplaced figures in the overview and falls back gracefully when an image fails", async () => {
    await renderStudio({ figures: [makeFigure("f-orphan", ["zzz"], { caption: "Orphan chart", label: "Figure 9", why_it_matters: "Shows the gap." })] });
    expect(await screen.findByText("Figures not used in the story")).toBeInTheDocument();
    const img = screen.getByAltText("Orphan chart");
    expect(img).toHaveAttribute("src", "http://api.test/papers/paper-1/figures/f-orphan.png");
    expect(screen.getByText("Shows the gap.")).toBeInTheDocument();
    expect(screen.getByText("Figure 9: Orphan chart")).toBeInTheDocument();
    expect(screen.getByText("From the paper, p. 3")).toBeInTheDocument();
    fireEvent.error(img);
    expect(screen.getByText(/image could not be loaded/i)).toBeInTheDocument();
    expect(screen.getByText("Figure 9: Orphan chart")).toBeInTheDocument();
  });

  it("shows the not-analyzed empty state with the Analyze panel", async () => {
    await renderStudio({ evidence: "missing" });
    expect(await screen.findByText("Not analyzed yet")).toBeInTheDocument();
    expect(screen.getByText("mock-analyze-panel")).toBeInTheDocument();
  });

  it("renders the wrapped panels for Ask, Citations, Learn and Re-analyze, and the raw Pages viewer", async () => {
    await renderStudio();
    await screen.findByText("Attention is enough.");
    const nav = within(screen.getByRole("navigation", { name: "Paper map" }));
    fireEvent.click(nav.getByRole("button", { name: "Ask" }));
    expect(screen.getByText("mock-assistant-panel")).toBeInTheDocument();
    fireEvent.click(nav.getByRole("button", { name: "Citations" }));
    expect(screen.getByText("mock-citations-panel")).toBeInTheDocument();
    fireEvent.click(nav.getByRole("button", { name: "Learn & Try" }));
    expect(screen.getByText("mock-learning-panel")).toBeInTheDocument();
    fireEvent.click(nav.getByRole("button", { name: "Deep report" }));
    expect(screen.getByText("mock-sections-Deep report")).toBeInTheDocument();
    fireEvent.click(nav.getByRole("button", { name: "Re-analyze" }));
    expect(screen.getByText("mock-analyze-panel")).toBeInTheDocument();
    fireEvent.click(nav.getByRole("button", { name: "Pages" }));
    expect(await screen.findByText("Raw page one text")).toBeInTheDocument();
  });
});

describe("Story", () => {
  it("renders typed sections with index, kicker, title, body, chips, visual, figures and closing", async () => {
    await renderStudio({ figures: [makeFigure("f1", ["c2"], { caption: "Model diagram" })] });
    fireEvent.click(tab("Story"));
    expect(await screen.findByText("Attention, unrolled")).toBeInTheDocument();
    expect(screen.getByText("A story about dropping recurrence.")).toBeInTheDocument();
    expect(screen.getByText("6 min")).toBeInTheDocument();
    expect(screen.getByText("01")).toBeInTheDocument();
    expect(screen.getByText("The problem")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recurrence is slow" })).toBeInTheDocument();
    expect(screen.getByText("First paragraph.")).toBeInTheDocument();
    expect(screen.getByText("Second paragraph.")).toBeInTheDocument();
    expect(screen.getByText("Headline")).toBeInTheDocument();
    const section1 = within(document.getElementById("story-section-s1") as HTMLElement);
    expect(section1.getByAltText("Model diagram")).toBeInTheDocument();
    expect(section1.getByRole("button", { name: /Source · p\. 2/ })).toBeInTheDocument();
    expect(screen.getByText("What to take away")).toBeInTheDocument();
  });

  it("chips open the overlay drawer; Escape closes it", async () => {
    await renderStudio();
    fireEvent.click(tab("Story"));
    await screen.findByText("Attention, unrolled");
    const chips = within(document.getElementById("story-section-s2") as HTMLElement);
    fireEvent.click(chips.getByRole("button", { name: /Source · p\. 5/ }));
    const drawer = screen.getByRole("complementary", { name: "Evidence" });
    expect(within(drawer).getByRole("heading", { name: "Trains faster" })).toBeInTheDocument();
    // Non-verified chips spell the status out in text, not only the dot colour.
    expect(chips.getByRole("button", { name: /mismatch/ })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("complementary", { name: "Evidence" })).toBeNull();
  });

  it("keeps the selected claim when switching modes", async () => {
    await renderStudio();
    await screen.findByText("Attention is enough.");
    fireEvent.click(within(screen.getByRole("list", { name: "Key findings" })).getByRole("button", { name: /Reaches 28.4 BLEU/ }));
    fireEvent.click(tab("Story"));
    await screen.findByText("Attention, unrolled");
    expect(within(screen.getByRole("complementary", { name: "Evidence" })).getByRole("heading", { name: "Reaches 28.4 BLEU" })).toBeInTheDocument();
  });

  it("falls back to a text-only story when only the plain story exists", async () => {
    await renderStudio({ spec: "missing", plain: true });
    fireEvent.click(tab("Story"));
    expect(await screen.findByRole("heading", { name: "Plain heading" })).toBeInTheDocument();
    expect(screen.getByText("Plain body text.")).toBeInTheDocument();
    expect(screen.getByText(/Text-only story/)).toBeInTheDocument();
    expect(screen.getByText("Reaches 28.4 BLEU")).toBeInTheDocument();
  });

  it("shows an empty state pointing to Re-analyze when there is no story", async () => {
    await renderStudio({ spec: "missing" });
    fireEvent.click(tab("Story"));
    expect(await screen.findByText("No story yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Go to Re-analyze" }));
    expect(tab("Lab")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("mock-analyze-panel")).toBeInTheDocument();
  });
});

describe("Preview", () => {
  it("tracks the active section with IntersectionObserver and shows its visual in the sticky pane", async () => {
    await renderStudio();
    fireEvent.click(tab("Preview"));
    await screen.findByText("Attention, unrolled");
    const pane = screen.getByRole("complementary", { name: "Visual for the current section" });
    expect(within(pane).getByText("Headline")).toBeInTheDocument();
    expect(document.getElementById("preview-section-s1")).toHaveAttribute("aria-current", "true");
    expect(document.getElementById("preview-section-s2")).not.toHaveAttribute("aria-current");

    act(() => {
      observerCallback?.([{ isIntersecting: true, target: document.getElementById("preview-section-s2") }]);
    });
    expect(document.getElementById("preview-section-s2")).toHaveAttribute("aria-current", "true");
    expect(document.getElementById("preview-section-s1")).not.toHaveAttribute("aria-current");
    expect(within(pane).getByText("We propose a new architecture", { exact: false })).toBeInTheDocument();
    expect(within(pane).queryByText("Headline")).toBeNull();
    expect(within(pane).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "2");
  });

  it("progress dots jump to a section", async () => {
    await renderStudio();
    fireEvent.click(tab("Preview"));
    await screen.findByText("Attention, unrolled");
    fireEvent.click(screen.getByRole("button", { name: "Go to section 02: Attention only" }));
    expect(document.getElementById("preview-section-s2")).toHaveAttribute("aria-current", "true");
  });

  it("opens the overlay drawer from a chip", async () => {
    await renderStudio();
    fireEvent.click(tab("Preview"));
    await screen.findByText("Attention, unrolled");
    fireEvent.click(within(document.getElementById("preview-section-s1") as HTMLElement).getByRole("button", { name: /Source · p\. 3/ }));
    expect(screen.getByRole("complementary", { name: "Evidence" })).toBeInTheDocument();
  });

  it("asks for a re-analysis when only a plain story exists", async () => {
    await renderStudio({ spec: "missing", plain: true });
    fireEvent.click(tab("Preview"));
    expect(await screen.findByText(/text-only one/)).toBeInTheDocument();
  });
});

describe("Code", () => {
  it("is held back for a later release: no Code tab", async () => {
    await renderStudio();
    await screen.findByText("Attention is enough.");
    expect(screen.queryByRole("tab", { name: "Code" })).toBeNull();
  });
});

describe("permalinks", () => {
  it("opens the claims ledger with the claim selected when the URL carries #claim-<id>", async () => {
    window.location.hash = "#claim-c2";
    setup();
    render(<PaperStudio paperId="paper-1" />);
    expect(await screen.findByText("3/4 verified")).toBeInTheDocument();
    expect(within(screen.getByRole("complementary", { name: "Evidence" })).getByRole("heading", { name: "Reaches 28.4 BLEU" })).toBeInTheDocument();
  });
});
