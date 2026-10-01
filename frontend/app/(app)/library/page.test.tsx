import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import LibraryPage from "./page";
import { deletePaper, getPapers } from "@/lib/papers-api";
import { matchesQuery } from "@/lib/paper-meta";
import type { PaperResponse } from "@/lib/paper-types";

vi.mock("@/lib/papers-api", () => ({
  getPapers: vi.fn(),
  getPaper: vi.fn(),
  deletePaper: vi.fn(),
}));

function paper(overrides: Partial<PaperResponse>): PaperResponse {
  return {
    id: "p",
    title: "Untitled",
    authors: [],
    year: null,
    venue: null,
    doi: null,
    arxiv_id: null,
    parse_status: "parsed",
    parse_error: null,
    created_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

const PAPERS = [
  paper({ id: "c", title: "Broken Scan", parse_status: "failed", parse_error: "Encrypted PDF", created_at: "2024-01-01T00:00:00Z" }),
  paper({ id: "a", title: "Attention Is All You Need", authors: ["Ashish Vaswani", "Noam Shazeer"], year: 2017, created_at: "2024-03-01T00:00:00Z" }),
  paper({ id: "b", title: "Réseaux de neurones", authors: ["José Álvarez"], year: 2020, created_at: "2024-02-01T00:00:00Z" }),
];

function confirmDelete(title: string): void {
  fireEvent.click(screen.getByRole("button", { name: `Delete ${title}` }));
  const group = screen.getByRole("group", { name: `Confirm deleting ${title}` });
  fireEvent.click(within(group).getByRole("button", { name: "Delete" }));
}

describe("LibraryPage", () => {
  beforeEach(() => {
    vi.mocked(getPapers).mockResolvedValue(PAPERS);
  });
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("shows every paper newest first with title link, authors, year, status and date", async () => {
    render(<LibraryPage />);
    const links = await screen.findAllByRole("link", { name: /Attention|Réseaux|Broken/ });
    expect(links.map((link) => link.textContent)).toEqual(["Attention Is All You Need", "Réseaux de neurones", "Broken Scan"]);
    expect(links[0]).toHaveAttribute("href", "/papers/a");
    expect(screen.getByText("Ashish Vaswani, Noam Shazeer")).toBeInTheDocument();
    expect(screen.getByText("2017")).toBeInTheDocument();
    expect(screen.getByText(/Encrypted PDF/)).toBeInTheDocument(); // failed status carries its text
    expect(screen.getAllByText(/^Added /)).toHaveLength(3);
  });

  it("filters by title or author, ignoring case and accents", async () => {
    render(<LibraryPage />);
    await screen.findByText("Attention Is All You Need");
    const search = screen.getByLabelText("Search papers");

    fireEvent.change(search, { target: { value: "reseaux" } });
    expect(screen.getByText("Réseaux de neurones")).toBeInTheDocument();
    expect(screen.queryByText("Attention Is All You Need")).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: "JOSE alvarez" } });
    expect(screen.getByText("Réseaux de neurones")).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "shazeer" } });
    expect(screen.getByText("Attention Is All You Need")).toBeInTheDocument();
    expect(screen.queryByText("Réseaux de neurones")).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: "zzz" } });
    expect(screen.getByText(/No papers match/)).toBeInTheDocument();
  });

  it("asks for confirmation before deleting, and Keep cancels", async () => {
    render(<LibraryPage />);
    await screen.findByText("Broken Scan");

    fireEvent.click(screen.getByRole("button", { name: "Delete Broken Scan" }));
    const group = screen.getByRole("group", { name: "Confirm deleting Broken Scan" });
    fireEvent.click(within(group).getByRole("button", { name: "Keep" }));

    expect(deletePaper).not.toHaveBeenCalled();
    expect(screen.getByText("Broken Scan")).toBeInTheDocument();
  });

  it("deletes after confirming and removes the card", async () => {
    vi.mocked(deletePaper).mockResolvedValue(undefined);
    render(<LibraryPage />);
    await screen.findByText("Broken Scan");

    confirmDelete("Broken Scan");

    await waitFor(() => expect(deletePaper).toHaveBeenCalledWith("c"));
    await waitFor(() => expect(screen.queryByText("Broken Scan")).not.toBeInTheDocument());
  });

  it("keeps the card and shows the error when delete fails", async () => {
    vi.mocked(deletePaper).mockRejectedValue(new Error("Server unavailable"));
    render(<LibraryPage />);
    await screen.findByText("Broken Scan");

    confirmDelete("Broken Scan");

    expect(await screen.findByRole("alert")).toHaveTextContent("Server unavailable");
    expect(screen.getByText("Broken Scan")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    vi.mocked(getPapers).mockResolvedValue([]);
    render(<LibraryPage />);
    expect(await screen.findByText(/No papers yet/)).toBeInTheDocument();
  });
});

describe("matchesQuery", () => {
  it("matches everything for a blank query", () => {
    expect(matchesQuery(PAPERS[0], "   ")).toBe(true);
  });
});
