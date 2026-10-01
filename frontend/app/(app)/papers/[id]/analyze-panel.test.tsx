import { afterEach, describe, expect, it, vi } from "vitest";
import { __resetProviderSelectionForTests } from "@/lib/provider-selection-store";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { AnalyzePanel } from "./analyze-panel";
import { getProviders } from "@/lib/providers-api";
import { streamAnalysis } from "@/lib/evidence-api";
import type { ProviderCatalogEntry } from "@/lib/provider-types";
import { __resetSessionModeForTests, useSessionMode } from "@/lib/session-mode-store";

vi.mock("@/lib/providers-api", () => ({
  getProviders: vi.fn(),
  getProviderModels: vi.fn().mockResolvedValue({ models: [{ id: "gemini-pro", label: "Gemini Pro", context_length: null, kind: "chat" }] }),
  testProviderModel: vi.fn(),
}));

vi.mock("@/lib/evidence-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/evidence-api")>("@/lib/evidence-api");
  return { ...actual, streamAnalysis: vi.fn() };
});

const PROVIDER: ProviderCatalogEntry = {
  id: "google",
  label: "Google Gemini",
  auth: "api_key",
  capabilities: ["generate", "stream", "embed", "vision"],
  implemented: true,
};

afterEach(() => {
  __resetProviderSelectionForTests();
});

describe("AnalyzePanel", () => {
  afterEach(() => {
    __resetSessionModeForTests();
  });

  it("marks the session as cloud once Analyze dispatches a request with a cloud provider", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(streamAnalysis).mockResolvedValueOnce(undefined);

    const session = renderHook(() => useSessionMode());
    expect(session.result.current).toBe("local");

    render(<AnalyzePanel paperId="paper-1" onAnalysisDone={() => {}} />);
    await screen.findByText("Google Gemini");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    await screen.findByRole("option", { name: "Gemini Pro" });
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    expect(session.result.current).toBe("cloud");
  });

  it("defaults to evidence-only, and lets the visual stage be added to the request", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(streamAnalysis).mockResolvedValueOnce(undefined);

    render(<AnalyzePanel paperId="paper-1" onAnalysisDone={() => {}} />);

    await screen.findByText("Google Gemini");
    fireEvent.click(screen.getByLabelText(/story \+ learning layer/i));
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    await screen.findByRole("option", { name: "Gemini Pro" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Analyze" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    expect(streamAnalysis).toHaveBeenCalledTimes(1);
    const [paperId, request] = vi.mocked(streamAnalysis).mock.calls[0];
    expect(paperId).toBe("paper-1");
    expect(Object.keys(request.stages).sort()).toEqual(["evidence", "visual"]);
    expect(request.stages.visual).toEqual({ provider_id: "google", api_key: "test-key", model: "gemini-pro" });
  });

  it("disables Analyze once every stage is unchecked", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);

    render(<AnalyzePanel paperId="paper-1" onAnalysisDone={() => {}} />);

    await screen.findByText("Google Gemini");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    fireEvent.click(screen.getByLabelText(/evidence \(claims/i));

    expect(screen.getByRole("button", { name: "Analyze" })).toBeDisabled();
  });
});
