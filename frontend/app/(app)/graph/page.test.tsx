import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __resetProviderSelectionForTests } from "@/lib/provider-selection-store";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import GraphPage from "./page";
import { getLibraryGraph } from "@/lib/graph-api";
import { getProviderModels, getProviders } from "@/lib/providers-api";
import type { ProviderCatalogEntry } from "@/lib/provider-types";
import { __resetSessionModeForTests, useSessionMode } from "@/lib/session-mode-store";

const EMBED_MODEL = { id: "text-embedding-3-small", label: "Text Embedding 3 Small", context_length: null, kind: "embedding" as const };

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/providers-api", () => ({
  getProviders: vi.fn(),
  getProviderModels: vi.fn().mockResolvedValue({ models: [] }),
  testProviderModel: vi.fn(),
}));
vi.mock("@/lib/graph-api", () => ({ getLibraryGraph: vi.fn() }));

// react-force-graph-3d touches WebGL, which jsdom can't provide.
vi.mock("react-force-graph-3d", () => ({ default: () => <div data-testid="force-graph-3d" /> }));

const PROVIDER: ProviderCatalogEntry = {
  id: "google",
  label: "Google Gemini",
  auth: "api_key",
  capabilities: ["generate", "stream", "embed", "vision"],
  implemented: true,
};

beforeEach(() => {
  vi.mocked(getProviderModels).mockResolvedValue({ models: [EMBED_MODEL] });
});

afterEach(() => {
  __resetProviderSelectionForTests();
});

describe("GraphPage", () => {
  afterEach(() => {
    __resetSessionModeForTests();
  });

  it("marks the session as cloud once View graph dispatches a request with a cloud provider", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(getLibraryGraph).mockResolvedValueOnce({ nodes: [], edges: [] });

    const session = renderHook(() => useSessionMode());
    expect(session.result.current).toBe("local");

    render(<GraphPage />);
    await screen.findByText("Google Gemini");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    await screen.findByRole("option", { name: "Text Embedding 3 Small" });
    await waitFor(() => expect(screen.getByRole("button", { name: "View graph" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "View graph" }));

    await screen.findByText("View graph");
    expect(session.result.current).toBe("cloud");
  });

  it("disables View graph until a provider, credential, and embedding model are filled in", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    render(<GraphPage />);
    await screen.findByText("Google Gemini");

    expect(screen.getByRole("button", { name: "View graph" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    expect(screen.getByRole("button", { name: "View graph" })).toBeDisabled(); // no embedding model chosen yet

    await screen.findByRole("option", { name: "Text Embedding 3 Small" });
    await waitFor(() => expect(screen.getByRole("button", { name: "View graph" })).not.toBeDisabled());
  });

  it("shows a clear message when there are analyzed papers but no edges yet", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(getLibraryGraph).mockResolvedValueOnce({
      nodes: [{ id: "paper-1", label: "Solo Paper", color: "#ff0000", size: null }],
      edges: [],
    });

    render(<GraphPage />);
    await screen.findByText("Google Gemini");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    await screen.findByRole("option", { name: "Text Embedding 3 Small" });
    await waitFor(() => expect(screen.getByRole("button", { name: "View graph" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "View graph" }));

    expect(await screen.findByText(/No connections yet\. Analyze more papers/)).toBeInTheDocument();
  });

  it("navigates to the paper reader when a node is clicked", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(getLibraryGraph).mockResolvedValueOnce({
      nodes: [{ id: "paper-1", label: "Solo Paper", color: "#ff0000", size: null }],
      edges: [],
    });

    render(<GraphPage />);
    await screen.findByText("Google Gemini");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    await screen.findByRole("option", { name: "Text Embedding 3 Small" });
    await waitFor(() => expect(screen.getByRole("button", { name: "View graph" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "View graph" }));

    fireEvent.click(await screen.findByRole("button", { name: "Solo Paper" }));
    expect(push).toHaveBeenCalledWith("/papers/paper-1");

    const [params] = vi.mocked(getLibraryGraph).mock.calls[0];
    expect(params).toEqual({ provider_id: "google", api_key: "test-key", embed_model: "text-embedding-3-small" });
  });
});
