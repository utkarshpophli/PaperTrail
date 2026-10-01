import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ResearchHomePage from "./page";
import { getPapers } from "@/lib/papers-api";
import type { PaperResponse } from "@/lib/paper-types";

vi.mock("@/components/composer/composer", () => ({ Composer: () => <div data-testid="composer" /> }));
vi.mock("@/lib/papers-api", () => ({ getPapers: vi.fn(), getPaper: vi.fn(), deletePaper: vi.fn() }));

function paper(n: number, overrides: Partial<PaperResponse> = {}): PaperResponse {
  return {
    id: `p${n}`,
    title: `Paper ${n}`,
    authors: [],
    year: null,
    venue: null,
    doi: null,
    arxiv_id: null,
    parse_status: "parsed",
    parse_error: null,
    created_at: `2024-01-${String(n).padStart(2, "0")}T00:00:00Z`,
    ...overrides,
  };
}

describe("ResearchHomePage", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("renders the composer and only the six newest papers with their status", async () => {
    const papers = Array.from({ length: 8 }, (_, i) => paper(i + 1));
    papers[7] = paper(8, { parse_status: "failed", parse_error: "Bad PDF" });
    vi.mocked(getPapers).mockResolvedValue(papers);

    render(<ResearchHomePage />);

    expect(screen.getByTestId("composer")).toBeInTheDocument();
    expect(await screen.findByText(/Bad PDF/)).toBeInTheDocument(); // newest paper, failed status text
    expect(screen.getAllByRole("listitem")).toHaveLength(6);
    expect(screen.getByText("Paper 7")).toBeInTheDocument();
    expect(screen.queryByText("Paper 2")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Paper 7" })).toHaveAttribute("href", "/papers/p7");
    // an unparsed paper is shown but not linked
    expect(screen.queryByRole("link", { name: "Paper 8" })).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no papers", async () => {
    vi.mocked(getPapers).mockResolvedValue([]);
    render(<ResearchHomePage />);
    expect(await screen.findByText(/No papers yet/)).toBeInTheDocument();
  });
});
