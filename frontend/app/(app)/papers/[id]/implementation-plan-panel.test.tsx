import { afterEach, describe, expect, it, vi } from "vitest";
import { __resetProviderSelectionForTests } from "@/lib/provider-selection-store";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ImplementationPlanPanel } from "./implementation-plan-panel";
import { getProviders } from "@/lib/providers-api";
import { generateImplementationPlan, getImplementationPlan } from "@/lib/evidence-api";
import type { ProviderCatalogEntry } from "@/lib/provider-types";
import type { ClaimResponse, GeneratedSectionResponse } from "@/lib/evidence-api";
import { ApiRequestError } from "@/lib/api-types";
import { getRepositories } from "@/lib/coderesearch-api";
import { __resetSessionModeForTests, useSessionMode } from "@/lib/session-mode-store";
import { renderHook } from "@testing-library/react";

vi.mock("@/lib/providers-api", () => ({
  getProviders: vi.fn(),
  getProviderModels: vi.fn().mockResolvedValue({ models: [{ id: "gemini-pro", label: "Gemini Pro", context_length: null, kind: "chat" }] }),
  testProviderModel: vi.fn(),
}));

vi.mock("@/lib/coderesearch-api", () => ({
  getRepositories: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/lib/evidence-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/evidence-api")>("@/lib/evidence-api");
  return { ...actual, generateImplementationPlan: vi.fn(), getImplementationPlan: vi.fn() };
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

const SECTION: GeneratedSectionResponse = {
  id: "section-1",
  title: "Setup",
  content: "Install dependencies, then reproduce the training loop.",
  order: 0,
  claim_ids: ["claim-1"],
  created_at: "2024-01-01T00:00:00Z",
};

afterEach(() => {
  __resetProviderSelectionForTests();
});

describe("ImplementationPlanPanel", () => {
  it("labels the plan as read-only guidance", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(getImplementationPlan).mockRejectedValueOnce(
      new ApiRequestError(404, { code: "implementation_plan_not_found", message: "Not found" }),
    );

    render(<ImplementationPlanPanel paperId="paper-1" claims={[CLAIM]} />);

    expect(screen.getByText(/never runs, applies, or modifies any/i)).toBeInTheDocument();
    expect(await screen.findByText(/not generated yet/i)).toBeInTheDocument();
  });

  it("generates a plan and displays the resulting sections with their claim sources", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([PROVIDER]);
    vi.mocked(getImplementationPlan)
      .mockRejectedValueOnce(new ApiRequestError(404, { code: "implementation_plan_not_found", message: "Not found" }))
      .mockResolvedValueOnce([SECTION]);
    vi.mocked(generateImplementationPlan).mockResolvedValueOnce([SECTION]);

    render(<ImplementationPlanPanel paperId="paper-1" claims={[CLAIM]} />);

    await screen.findByText("Google Gemini");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
    await screen.findByRole("option", { name: "Gemini Pro" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate plan" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Generate plan" }));

    await waitFor(() =>
      expect(generateImplementationPlan).toHaveBeenCalledWith("paper-1", {
        provider_id: "google",
        api_key: "test-key",
        model: "gemini-pro",
      }),
    );

    expect(await screen.findByText("Setup")).toBeInTheDocument();
    expect(screen.getByText("Install dependencies, then reproduce the training loop.")).toBeInTheDocument();
    expect(screen.getByText(CLAIM.statement)).toBeInTheDocument();
  });

  describe("external egress (README fetch from a linked repo)", () => {
    async function generate() {
      vi.mocked(getProviders).mockResolvedValueOnce([{ ...PROVIDER, id: "ollama", label: "Ollama", auth: "none" }]);
      vi.mocked(getImplementationPlan).mockRejectedValue(
        new ApiRequestError(404, { code: "implementation_plan_not_found", message: "Not found" }),
      );
      vi.mocked(generateImplementationPlan).mockResolvedValueOnce([SECTION]);
      render(<ImplementationPlanPanel paperId="paper-1" claims={[CLAIM]} />);
      await screen.findByRole("option", { name: /Ollama/ });
      fireEvent.change(screen.getByLabelText("Endpoint"), { target: { value: "http://localhost:11434" } });
      await screen.findByRole("option", { name: "Gemini Pro" });
      await waitFor(() => expect(screen.getByRole("button", { name: /generate/i })).not.toBeDisabled());
      fireEvent.click(screen.getByRole("button", { name: /generate/i }));
      await waitFor(() => expect(generateImplementationPlan).toHaveBeenCalled());
    }

    it("stays local with a local provider and no linked repository", async () => {
      __resetSessionModeForTests();
      vi.mocked(getRepositories).mockResolvedValueOnce([]);
      const { result } = renderHook(() => useSessionMode());
      await generate();
      expect(result.current).toBe("local");
    });

    it("flips to external with a local provider when a repository is linked", async () => {
      __resetSessionModeForTests();
      vi.mocked(getRepositories).mockResolvedValueOnce([{ id: "r1" } as never]);
      const { result } = renderHook(() => useSessionMode());
      await generate();
      await waitFor(() => expect(result.current).toBe("cloud"));
    });
  });
});
