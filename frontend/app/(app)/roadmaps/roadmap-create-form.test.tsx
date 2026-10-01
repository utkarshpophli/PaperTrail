import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __resetProviderSelectionForTests } from "@/lib/provider-selection-store";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RoadmapCreateForm } from "./roadmap-create-form";
import { getProviderModels, getProviders } from "@/lib/providers-api";
import { getPapers } from "@/lib/papers-api";
import { streamRoadmap } from "@/lib/discovery-api";
import type { ProviderCatalogEntry } from "@/lib/provider-types";
import type { PaperResponse } from "@/lib/paper-types";

const CHAT_MODEL = { id: "gemini-pro", label: "Gemini Pro", context_length: null, kind: "chat" as const };
const EMBED_MODEL = { id: "text-embedding-3-small", label: "Text Embedding 3 Small", context_length: null, kind: "embedding" as const };

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

vi.mock("@/lib/providers-api", () => ({
  getProviders: vi.fn(),
  getProviderModels: vi.fn().mockResolvedValue({ models: [] }),
  testProviderModel: vi.fn(),
}));
vi.mock("@/lib/papers-api", () => ({ getPapers: vi.fn() }));
vi.mock("@/lib/discovery-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/discovery-api")>("@/lib/discovery-api");
  return { ...actual, streamRoadmap: vi.fn() };
});

const PROVIDER: ProviderCatalogEntry = {
  id: "google",
  label: "Google Gemini",
  auth: "api_key",
  capabilities: ["generate", "stream", "embed", "vision"],
  implemented: true,
};

const PAPER: PaperResponse = {
  id: "paper-1",
  title: "Denoising Diffusion Probabilistic Models",
  authors: ["J. Ho"],
  year: 2020,
  venue: null,
  doi: null,
  arxiv_id: "2006.11239",
  parse_status: "parsed",
  parse_error: null,
  created_at: "2024-01-01T00:00:00Z",
};

beforeEach(() => {
  vi.mocked(getProviderModels).mockImplementation((_id, _creds, _signal, kind) =>
    Promise.resolve(kind === "embedding" ? { models: [EMBED_MODEL] } : { models: [CHAT_MODEL] }),
  );
});

afterEach(() => {
  __resetProviderSelectionForTests();
});

async function fillModels(): Promise<void> {
  await screen.findByRole("option", { name: "Gemini Pro" });
  await screen.findByRole("option", { name: "Text Embedding 3 Small" });
}

describe("RoadmapCreateForm", () => {
  it("disables Create roadmap until a topic, provider, credential, and both models are all filled in", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(getPapers).mockResolvedValueOnce([]);

    render(<RoadmapCreateForm />);
    await screen.findByText("Google Gemini");

    const createButton = screen.getByRole("button", { name: "Create roadmap" });
    expect(createButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    expect(createButton).toBeDisabled(); // topic still empty

    fireEvent.change(screen.getByPlaceholderText("e.g. diffusion models"), { target: { value: "diffusion models" } });
    expect(createButton).toBeDisabled(); // models not loaded/chosen yet

    await fillModels();
    await waitFor(() => expect(createButton).not.toBeDisabled());
  });

  it("requires selecting a paper (not a topic) when the 'An owned paper' target is chosen", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(getPapers).mockResolvedValueOnce([PAPER]);

    render(<RoadmapCreateForm />);
    await screen.findByText("Google Gemini");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    fireEvent.click(screen.getByLabelText("An owned paper"));
    await fillModels();

    const createButton = screen.getByRole("button", { name: "Create roadmap" });
    expect(createButton).toBeDisabled(); // no paper selected yet

    fireEvent.change(screen.getByLabelText("Target paper"), { target: { value: "paper-1" } });
    await waitFor(() => expect(createButton).not.toBeDisabled());
  });

  it("streams a {type:'paper', paper_id} target and redirects to the new roadmap on success", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(getPapers).mockResolvedValueOnce([PAPER]);
    vi.mocked(streamRoadmap).mockImplementationOnce(async (_request, onEvent) => {
      onEvent({
        type: "done",
        stage: null,
        message: null,
        data: {
          id: "roadmap-1",
          target_description: PAPER.title,
          target_paper_id: PAPER.id,
          concepts: [],
          edges: [],
          milestones: [],
          overview: "overview",
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
        },
      });
    });

    render(<RoadmapCreateForm />);
    await screen.findByText("Google Gemini");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    fireEvent.click(screen.getByLabelText("An owned paper"));
    fireEvent.change(screen.getByLabelText("Target paper"), { target: { value: "paper-1" } });
    await fillModels();
    await waitFor(() => expect(screen.getByRole("button", { name: "Create roadmap" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Create roadmap" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/roadmaps/roadmap-1"));
    const [request] = vi.mocked(streamRoadmap).mock.calls[0];
    expect(request.target).toEqual({ type: "paper", paper_id: "paper-1" });
    expect(request.model).toBe("gemini-pro");
    expect(request.embed_model).toBe("text-embedding-3-small");
  });
});
