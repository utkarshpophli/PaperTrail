import { afterEach, describe, expect, it, vi } from "vitest";
import { __resetProviderSelectionForTests } from "@/lib/provider-selection-store";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { AssistantPanel } from "./assistant-panel";
import { getProviders } from "@/lib/providers-api";
import { getPapers } from "@/lib/papers-api";
import { getClaim, streamAssistant, type AnalysisEvent } from "@/lib/evidence-api";
import type { ProviderCatalogEntry } from "@/lib/provider-types";
import type { PaperResponse } from "@/lib/paper-types";
import type { ClaimResponse } from "@/lib/evidence-api";
import { __resetSessionModeForTests, useSessionMode } from "@/lib/session-mode-store";

vi.mock("@/lib/providers-api", () => ({
  getProviders: vi.fn(),
  getProviderModels: vi.fn().mockResolvedValue({ models: [{ id: "gemini-pro", label: "Gemini Pro", context_length: null, kind: "chat" }] }),
  testProviderModel: vi.fn(),
}));

vi.mock("@/lib/papers-api", () => ({
  getPapers: vi.fn(),
}));

vi.mock("@/lib/evidence-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/evidence-api")>("@/lib/evidence-api");
  return { ...actual, streamAssistant: vi.fn(), getClaim: vi.fn() };
});

const PROVIDER: ProviderCatalogEntry = {
  id: "google",
  label: "Google Gemini",
  auth: "api_key",
  capabilities: ["generate", "stream", "embed", "vision"],
  implemented: true,
};

const CLAIM: ClaimResponse = {
  id: "claim-1",
  statement: "The model achieves 90% accuracy.",
  kind: "reported-result",
  verification_status: "verified",
  source_refs: [{ id: "ref-1", page: 3, excerpt: "90% accuracy", locator: null }],
  created_at: "2024-01-01T00:00:00Z",
};

afterEach(() => {
  __resetProviderSelectionForTests();
});

describe("AssistantPanel", () => {
  afterEach(() => {
    __resetSessionModeForTests();
  });

  it("streams an answer, resolves its cited claim ids for display, and marks the session as cloud", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(getClaim).mockResolvedValueOnce(CLAIM);
    vi.mocked(streamAssistant).mockImplementationOnce(async (_paperId, _request, onEvent) => {
      const events: AnalysisEvent[] = [
        { type: "progress", stage: "assistant", message: "Thinking…", data: null },
        { type: "done", stage: "assistant", message: null, data: { answer: "It reports 90% accuracy.", claim_ids: ["claim-1"] } },
      ];
      events.forEach(onEvent);
    });

    const session = renderHook(() => useSessionMode());
    render(<AssistantPanel paperId="paper-1" />);

    await screen.findByText("Google Gemini");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    await screen.findByRole("option", { name: "Gemini Pro" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    await screen.findByText("It reports 90% accuracy.");
    expect(await screen.findByText("The model achieves 90% accuracy.")).toBeInTheDocument();
    expect(getClaim).toHaveBeenCalledWith("paper-1", "claim-1");

    const [paperId, request] = vi.mocked(streamAssistant).mock.calls[0];
    expect(paperId).toBe("paper-1");
    expect(request).toEqual({ action: "understand", provider_id: "google", api_key: "test-key", model: "gemini-pro" });
    expect(session.result.current).toBe("cloud");
  });

  it("requires at least one compare paper selected before Ask is enabled", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    const otherPaper: PaperResponse = {
      id: "paper-2",
      title: "Another Paper",
      authors: [],
      year: null,
      venue: null,
      doi: null,
      arxiv_id: null,
      parse_status: "parsed",
      parse_error: null,
      created_at: "2024-01-01T00:00:00Z",
    };
    vi.mocked(getPapers).mockResolvedValueOnce([otherPaper]);

    render(<AssistantPanel paperId="paper-1" />);

    await screen.findByText("Google Gemini");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    await screen.findByRole("option", { name: "Gemini Pro" });
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "compare" } });

    await screen.findByText("Another Paper");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(screen.getByText("Select at least one paper to compare against.")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Another Paper"));

    await waitFor(() => expect(screen.getByRole("button", { name: "Ask" })).not.toBeDisabled());
    expect(streamAssistant).not.toHaveBeenCalled();
  });
});
