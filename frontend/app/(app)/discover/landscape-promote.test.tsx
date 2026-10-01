import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LandscapePromote } from "./landscape-promote";
import { listCollections } from "@/lib/collections-api";
import { promoteLandscape } from "@/lib/discovery-api";

vi.mock("@/lib/collections-api", () => ({ listCollections: vi.fn() }));
vi.mock("@/lib/discovery-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/discovery-api")>("@/lib/discovery-api");
  return { ...actual, promoteLandscape: vi.fn() };
});

describe("LandscapePromote", () => {
  it("disables Save until an existing collection is chosen or a new name is typed", async () => {
    vi.mocked(listCollections).mockResolvedValueOnce([]);
    render(<LandscapePromote landscapeId="landscape-1" />);
    await waitFor(() => expect(listCollections).toHaveBeenCalled());

    expect(screen.getByRole("button", { name: "Save to collection" })).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("New collection name"), { target: { value: "RAG papers" } });
    expect(screen.getByRole("button", { name: "Save to collection" })).not.toBeDisabled();
  });

  it("promotes into a new collection and shows the added/skipped split, never hiding skipped ids", async () => {
    vi.mocked(listCollections).mockResolvedValueOnce([]);
    vi.mocked(promoteLandscape).mockResolvedValueOnce({
      collection_id: "collection-1",
      added: ["1234.5678"],
      skipped_not_ingested: ["9999.0001"],
    });

    render(<LandscapePromote landscapeId="landscape-1" />);
    await waitFor(() => expect(listCollections).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText("New collection name"), { target: { value: "RAG papers" } });
    fireEvent.click(screen.getByRole("button", { name: "Save to collection" }));

    expect(await screen.findByText(/1 paper added/)).toHaveTextContent(
      "1 paper added, 1 skipped (not yet in your library): 9999.0001.",
    );
    expect(promoteLandscape).toHaveBeenCalledWith("landscape-1", { collection_name: "RAG papers" });
  });

  it("promotes into an existing collection by id, not name", async () => {
    vi.mocked(listCollections).mockResolvedValueOnce([
      { id: "collection-1", name: "RAG papers", paper_ids: [], created_at: "x", updated_at: "x" },
    ]);
    vi.mocked(promoteLandscape).mockResolvedValueOnce({
      collection_id: "collection-1",
      added: ["1234.5678"],
      skipped_not_ingested: [],
    });

    render(<LandscapePromote landscapeId="landscape-1" />);
    await screen.findByText("RAG papers");

    fireEvent.change(screen.getByLabelText("Existing collection"), { target: { value: "collection-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save to collection" }));

    await waitFor(() =>
      expect(promoteLandscape).toHaveBeenCalledWith("landscape-1", { collection_id: "collection-1" }),
    );
    expect(await screen.findByText("1 paper added.")).toBeInTheDocument();
  });
});
