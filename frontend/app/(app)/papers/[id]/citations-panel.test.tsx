import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __resetProviderSelectionForTests } from "@/lib/provider-selection-store";
import { OTHER_MODEL_VALUE } from "@/components/provider-picker";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { CitationsPanel } from "./citations-panel";
import { getProviderModels, getProviders } from "@/lib/providers-api";
import { getPapers } from "@/lib/papers-api";
import { refreshCitations, type CitationEdge } from "@/lib/graph-api";
import type { ProviderCatalogEntry } from "@/lib/provider-types";
import type { PaperResponse } from "@/lib/paper-types";
import { ApiRequestError } from "@/lib/api-types";
import { __resetSessionModeForTests, useSessionMode } from "@/lib/session-mode-store";

vi.mock("@/lib/providers-api", () => ({
  getProviders: vi.fn(),
  getProviderModels: vi.fn().mockResolvedValue({ models: [] }),
  testProviderModel: vi.fn(),
}));
vi.mock("@/lib/papers-api", () => ({ getPapers: vi.fn() }));
vi.mock("@/lib/graph-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/graph-api")>("@/lib/graph-api");
  return { ...actual, refreshCitations: vi.fn() };
});

const CLOUD: ProviderCatalogEntry = {
  id: "google",
  label: "Google Gemini",
  auth: "api_key",
  capabilities: ["generate", "stream", "embed", "vision"],
  implemented: true,
};

const LOCAL: ProviderCatalogEntry = {
  id: "ollama",
  label: "Ollama",
  auth: "none",
  capabilities: ["generate", "stream", "embed"],
  implemented: true,
};

function paper(id: string, title: string): PaperResponse {
  return {
    id,
    title,
    authors: [],
    year: null,
    venue: null,
    doi: null,
    arxiv_id: null,
    parse_status: "parsed",
    parse_error: null,
    created_at: "2024-01-01T00:00:00Z",
  };
}

function edge(overrides: Partial<CitationEdge>): CitationEdge {
  return {
    id: "e1",
    from_paper_id: "paper-1",
    to_paper_id: "paper-2",
    relation: "cites",
    confidence: 1,
    openalex_work_id: "W1",
    fetched_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

const MODEL = { id: "gemini-pro", label: "Gemini Pro", context_length: null, kind: "chat" as const };

async function submitWithCloud(credential: string): Promise<void> {
  await screen.findByText("Google Gemini");
  fireEvent.change(screen.getByLabelText("API key"), { target: { value: credential } });
  await screen.findByRole("option", { name: "Gemini Pro" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Refresh citations" })).not.toBeDisabled());
  fireEvent.click(screen.getByRole("button", { name: "Refresh citations" }));
}

beforeEach(() => {
  vi.mocked(getProviderModels).mockResolvedValue({ models: [MODEL] });
});

afterEach(() => {
  __resetProviderSelectionForTests();
});

describe("CitationsPanel", () => {
  afterEach(() => {
    __resetSessionModeForTests();
    vi.resetAllMocks();
  });

  it("discloses the OpenAlex egress before the button is used", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([CLOUD]);
    render(<CitationsPanel paperId="paper-1" />);

    expect(
      screen.getByText(
        "Sends this paper's and your other papers' titles/DOIs to OpenAlex (api.openalex.org), even when using a local model.",
      ),
    ).toBeInTheDocument();
    await screen.findByText("Google Gemini");
  });

  it("refreshes, resolves the other paper's title, and labels record vs AI-classified edges differently", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([CLOUD]);
    vi.mocked(getPapers).mockResolvedValueOnce([paper("paper-2", "Dense Retrieval"), paper("paper-3", "Old Baseline")]);
    vi.mocked(refreshCitations).mockResolvedValueOnce([
      edge({ id: "e1", to_paper_id: "paper-2", relation: "cites", confidence: 1 }),
      edge({ id: "e2", from_paper_id: "paper-3", to_paper_id: "paper-1", relation: "extends", confidence: 0.72 }),
    ]);

    render(<CitationsPanel paperId="paper-1" />);
    await submitWithCloud("test-key");

    await waitFor(() =>
      expect(refreshCitations).toHaveBeenCalledWith("paper-1", {
        provider_id: "google",
        api_key: "test-key",
        model: "gemini-pro",
      }),
    );

    expect(await screen.findByText("this paper → Dense Retrieval")).toBeInTheDocument();
    expect(screen.getByText("Old Baseline → this paper")).toBeInTheDocument();
    expect(screen.getByText("Cites")).toBeInTheDocument();
    expect(screen.getByText("Extends")).toBeInTheDocument();
    // Plain cites is an external record; a refined relation is a guess with its own confidence.
    expect(screen.getByText("Citation record (OpenAlex)")).toBeInTheDocument();
    expect(screen.getByText("AI-classified, 72% confidence")).toBeInTheDocument();
    expect(screen.getAllByText(/AI-classified/)).toHaveLength(1);
  });

  it("sends a local provider's endpoint (not an api_key) and the optional model", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([LOCAL]);
    vi.mocked(getPapers).mockResolvedValueOnce([]);
    vi.mocked(refreshCitations).mockResolvedValueOnce([]);

    render(<CitationsPanel paperId="paper-1" />);
    await screen.findByText("Ollama");
    fireEvent.change(screen.getByLabelText("Endpoint"), { target: { value: "http://localhost:11434" } });
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: OTHER_MODEL_VALUE } });
    fireEvent.change(screen.getByLabelText("Other model id"), { target: { value: "llama3" } });
    fireEvent.click(screen.getByRole("button", { name: "Refresh citations" }));

    await waitFor(() =>
      expect(refreshCitations).toHaveBeenCalledWith("paper-1", {
        provider_id: "ollama",
        endpoint: "http://localhost:11434",
        model: "llama3",
      }),
    );
  });

  it("shows the explicit empty state when OpenAlex yields no edges", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([CLOUD]);
    vi.mocked(getPapers).mockResolvedValueOnce([]);
    vi.mocked(refreshCitations).mockResolvedValueOnce([]);

    render(<CitationsPanel paperId="paper-1" />);
    await submitWithCloud("test-key");

    expect(
      await screen.findByText("OpenAlex has no record of this paper, or none of your other papers are cited by it."),
    ).toBeInTheDocument();
  });

  it("shows a specific rate-limit message on 429", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([CLOUD]);
    vi.mocked(refreshCitations).mockRejectedValueOnce(
      new ApiRequestError(429, { code: "rate_limited", message: "Too many requests" }),
    );

    render(<CitationsPanel paperId="paper-1" />);
    await submitWithCloud("test-key");

    expect(await screen.findByRole("alert")).toHaveTextContent(/citation refresh rate limit \(5 per hour\)/i);
  });

  it("shows a specific OpenAlex-unavailable message on 502", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([CLOUD]);
    vi.mocked(refreshCitations).mockRejectedValueOnce(
      new ApiRequestError(502, { code: "openalex_unavailable", message: "OpenAlex timed out" }),
    );

    render(<CitationsPanel paperId="paper-1" />);
    await submitWithCloud("test-key");

    expect(await screen.findByRole("alert")).toHaveTextContent(/OpenAlex could not be reached/i);
  });

  it("surfaces the backend message for other failures such as paper_not_found", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([CLOUD]);
    vi.mocked(refreshCitations).mockRejectedValueOnce(
      new ApiRequestError(404, { code: "paper_not_found", message: "Paper not found" }),
    );

    render(<CitationsPanel paperId="paper-1" />);
    await submitWithCloud("test-key");

    expect(await screen.findByRole("alert")).toHaveTextContent("Paper not found");
  });

  it("flips the session indicator on dispatch even with a local provider (OpenAlex egress), not on selection", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([LOCAL]);
    vi.mocked(getPapers).mockResolvedValueOnce([]);
    vi.mocked(refreshCitations).mockResolvedValueOnce([]);
    const session = renderHook(() => useSessionMode());

    render(<CitationsPanel paperId="paper-1" />);
    await screen.findByText("Ollama");
    fireEvent.change(screen.getByLabelText("Endpoint"), { target: { value: "http://localhost:11434" } });
    expect(session.result.current).toBe("local");

    await screen.findByRole("option", { name: "Gemini Pro" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh citations" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Refresh citations" }));

    await waitFor(() => expect(refreshCitations).toHaveBeenCalled());
    expect(session.result.current).toBe("cloud");
  });
});
