import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CollectionCreateForm } from "./collection-create-form";
import { createCollection } from "@/lib/collections-api";

vi.mock("@/lib/collections-api", () => ({ createCollection: vi.fn() }));

describe("CollectionCreateForm", () => {
  it("disables the create button until a name is entered", () => {
    render(<CollectionCreateForm onCreated={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Create collection" })).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("e.g. Diffusion models"), { target: { value: "RAG papers" } });
    expect(screen.getByRole("button", { name: "Create collection" })).not.toBeDisabled();
  });

  it("creates a collection and reports it back, clearing the input", async () => {
    const created = { id: "collection-1", name: "RAG papers", paper_ids: [], created_at: "x", updated_at: "x" };
    vi.mocked(createCollection).mockResolvedValueOnce(created);
    const onCreated = vi.fn();

    render(<CollectionCreateForm onCreated={onCreated} />);
    fireEvent.change(screen.getByPlaceholderText("e.g. Diffusion models"), { target: { value: "RAG papers" } });
    fireEvent.click(screen.getByRole("button", { name: "Create collection" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
    expect(createCollection).toHaveBeenCalledWith("RAG papers");
    expect(screen.getByPlaceholderText("e.g. Diffusion models")).toHaveValue("");
  });

  it("shows an error message when creation fails", async () => {
    vi.mocked(createCollection).mockRejectedValueOnce(new Error("boom"));

    render(<CollectionCreateForm onCreated={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText("e.g. Diffusion models"), { target: { value: "RAG papers" } });
    fireEvent.click(screen.getByRole("button", { name: "Create collection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});
