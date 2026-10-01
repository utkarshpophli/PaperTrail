import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __resetProviderSelectionForTests } from "@/lib/provider-selection-store";
import { OTHER_MODEL_VALUE } from "@/components/provider-picker";
import { fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { CodeLinksPanel } from "./code-links-panel";
import {
  deleteCodeLink,
  getCodeLinks,
  getRepositories,
  linkClaimToCode,
  type CodeLink,
  type Repository,
} from "@/lib/coderesearch-api";
import { getProviderModels, getProviders } from "@/lib/providers-api";
import type { ClaimResponse } from "@/lib/evidence-api";
import type { ProviderCatalogEntry } from "@/lib/provider-types";
import { ApiRequestError } from "@/lib/api-types";
import { __resetSessionModeForTests, useSessionMode } from "@/lib/session-mode-store";

vi.mock("@/lib/providers-api", () => ({
  getProviders: vi.fn(),
  getProviderModels: vi.fn().mockResolvedValue({ models: [] }),
  testProviderModel: vi.fn(),
}));
vi.mock("@/lib/coderesearch-api", () => ({
  getRepositories: vi.fn(),
  getCodeLinks: vi.fn(),
  linkClaimToCode: vi.fn(),
  deleteCodeLink: vi.fn(),
}));

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

const REPO: Repository = {
  id: "repo-1",
  paper_id: "paper-1",
  url: "https://github.com/owner/repo",
  owner: "owner",
  name: "repo",
  description: null,
  stars: null,
  source: "user_linked",
  confidence: null,
  created_at: "2024-01-01T00:00:00Z",
};

function claim(id: string, kind: ClaimResponse["kind"], statement: string): ClaimResponse {
  return { id, statement, kind, verification_status: "verified", source_refs: [], created_at: "2024-01-01T00:00:00Z" };
}

const CLAIMS: ClaimResponse[] = [
  claim("c-method", "method", "Uses multi-head attention."),
  claim("c-result", "reported-result", "Reaches 28.4 BLEU."),
  claim("c-bg", "background", "Background sentence."),
  claim("c-lim", "limitation", "Limitation sentence."),
  claim("c-interp", "author-interpretation", "Interpretation sentence."),
];

function codeLink(overrides: Partial<CodeLink>): CodeLink {
  return {
    id: "l1",
    paper_id: "paper-1",
    repository_id: "repo-1",
    claim_id: "c-method",
    file_path: "src/attention.py",
    start_line: 10,
    end_line: 14,
    excerpt: "def attention(q, k, v): ...",
    verification_status: "verified",
    explanation: "Implements scaled dot-product attention.",
    created_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

async function renderPanel(provider: ProviderCatalogEntry, existing: CodeLink[] = []): Promise<void> {
  vi.mocked(getProviders).mockResolvedValueOnce([provider]);
  vi.mocked(getRepositories).mockResolvedValueOnce([REPO]);
  vi.mocked(getCodeLinks).mockResolvedValueOnce(existing);
  render(<CodeLinksPanel paperId="paper-1" claims={CLAIMS} />);
  await screen.findByText(provider.label);
  await screen.findByText("owner/repo");
}

async function fillCloudAndFind(claimStatement: string): Promise<void> {
  fireEvent.change(screen.getByLabelText("API key"), { target: { value: "test-key" } });
  await screen.findByRole("option", { name: "Gemini Pro" });
  const row = screen.getByText(claimStatement).closest("li") as HTMLElement;
  await waitFor(() => expect(within(row).getByRole("button", { name: "Find implementing code" })).not.toBeDisabled());
  fireEvent.click(within(row).getByRole("button", { name: "Find implementing code" }));
}

const MODEL = { id: "gemini-pro", label: "Gemini Pro", context_length: null, kind: "chat" as const };

beforeEach(() => {
  vi.mocked(getProviderModels).mockResolvedValue({ models: [MODEL] });
});

afterEach(() => {
  __resetProviderSelectionForTests();
});

describe("CodeLinksPanel", () => {
  afterEach(() => {
    __resetSessionModeForTests();
    vi.resetAllMocks();
  });

  it("lists only method and reported-result claims, with the caption and disclosure", async () => {
    await renderPanel(CLOUD);

    expect(screen.getByText("Uses multi-head attention.")).toBeInTheDocument();
    expect(screen.getByText("Reaches 28.4 BLEU.")).toBeInTheDocument();
    expect(screen.queryByText("Background sentence.")).not.toBeInTheDocument();
    expect(screen.queryByText("Limitation sentence.")).not.toBeInTheDocument();
    expect(screen.queryByText("Interpretation sentence.")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Shows where matching code appears in the repository; it does not prove the code implements the claim.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Fetches repository files from GitHub and sends their contents to the selected AI provider."),
    ).toBeInTheDocument();
  });

  it("sends api_key, model and GitHub token for a cloud provider", async () => {
    await renderPanel(CLOUD);
    vi.mocked(linkClaimToCode).mockResolvedValueOnce([]);
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: OTHER_MODEL_VALUE } });
    fireEvent.change(screen.getByLabelText("Other model id"), { target: { value: "gemini-pro" } });
    fireEvent.change(screen.getByLabelText("GitHub token (optional)"), { target: { value: "ghp_x" } });
    expect(screen.getByLabelText("GitHub token (optional)")).toHaveAttribute("type", "password");
    await fillCloudAndFind("Uses multi-head attention.");

    await waitFor(() =>
      expect(linkClaimToCode).toHaveBeenCalledWith("paper-1", "repo-1", {
        claim_id: "c-method",
        provider_id: "google",
        api_key: "test-key",
        model: "gemini-pro",
        token: "ghp_x",
      }),
    );
    expect(await screen.findByText("No matching code was proposed for this claim in this repository.")).toBeInTheDocument();
  });

  it("sends endpoint (not api_key) and omits the token when blank for a local provider", async () => {
    await renderPanel(LOCAL);
    vi.mocked(linkClaimToCode).mockResolvedValueOnce([]);
    fireEvent.change(screen.getByLabelText("Endpoint"), { target: { value: "http://localhost:11434" } });
    await screen.findByRole("option", { name: "Gemini Pro" });
    fireEvent.click(
      within(screen.getByText("Reaches 28.4 BLEU.").closest("li") as HTMLElement).getByRole("button", {
        name: "Find implementing code",
      }),
    );

    await waitFor(() =>
      expect(linkClaimToCode).toHaveBeenCalledWith("paper-1", "repo-1", {
        claim_id: "c-result",
        provider_id: "ollama",
        endpoint: "http://localhost:11434",
        model: "gemini-pro",
      }),
    );
  });

  it("renders a verified link with its line range and a not-found link with no fake range", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([CLOUD]);
    vi.mocked(getRepositories).mockResolvedValueOnce([REPO]);
    vi.mocked(getCodeLinks).mockResolvedValueOnce([
      codeLink({ id: "ok", file_path: "src/attention.py", start_line: 10, end_line: 14 }),
      codeLink({
        id: "bad",
        claim_id: "c-result",
        file_path: "src/bleu.py",
        start_line: 1,
        end_line: 1,
        verification_status: "not-found",
      }),
    ]);
    render(<CodeLinksPanel paperId="paper-1" claims={CLAIMS} />);

    const ok = (await screen.findByText(/src\/attention\.py/)).closest("li") as HTMLElement;
    expect(ok).toHaveTextContent("L10–14");
    expect(within(ok).getByText("Excerpt found in file")).toBeInTheDocument();
    expect(within(ok).getByText("Verified")).toBeInTheDocument();

    const bad = screen.getByText(/src\/bleu\.py/).closest("li") as HTMLElement;
    expect(bad).toHaveTextContent("line unknown");
    expect(bad).not.toHaveTextContent("L1–1");
    expect(within(bad).getByText("Excerpt not found in file: needs review")).toBeInTheDocument();
    expect(within(bad).getByText("Not found")).toBeInTheDocument();
  });

  it("renders excerpt and explanation as literal text, never parsed as HTML", async () => {
    const payload = '<script>window.__pwned = true</script><img src=x onerror="window.__pwned = true">';
    await renderPanel(CLOUD, [codeLink({ excerpt: payload, explanation: `<b>bold</b> ${payload}` })]);

    const pre = (await screen.findByText(payload)).closest("pre") as HTMLElement;
    expect(pre.tagName).toBe("PRE");
    expect(pre.querySelector("script, img")).toBeNull();
    expect(screen.getByText(`<b>bold</b> ${payload}`)).toBeInTheDocument();
    expect(document.querySelector("li script, li img, li b")).toBeNull();
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  it("replaces existing links for the claim with the returned ones", async () => {
    await renderPanel(CLOUD, [codeLink({ id: "old", file_path: "old/path.py" })]);
    vi.mocked(linkClaimToCode).mockResolvedValueOnce([codeLink({ id: "new", file_path: "new/path.py" })]);
    await fillCloudAndFind("Uses multi-head attention.");

    expect(await screen.findByText(/new\/path\.py/)).toBeInTheDocument();
    expect(screen.queryByText(/old\/path\.py/)).not.toBeInTheDocument();
  });

  it("deletes a link", async () => {
    await renderPanel(CLOUD, [codeLink({ id: "l1" })]);
    vi.mocked(deleteCodeLink).mockResolvedValueOnce(undefined);

    fireEvent.click(await screen.findByRole("button", { name: "Delete link" }));

    await waitFor(() => expect(deleteCodeLink).toHaveBeenCalledWith("paper-1", "l1"));
    await waitFor(() => expect(screen.queryByText(/src\/attention\.py/)).not.toBeInTheDocument());
  });

  it("shows a specific message on 429", async () => {
    await renderPanel(CLOUD);
    vi.mocked(linkClaimToCode).mockRejectedValueOnce(
      new ApiRequestError(429, { code: "rate_limited", message: "Too many requests" }),
    );
    await fillCloudAndFind("Uses multi-head attention.");

    expect(await screen.findByRole("alert")).toHaveTextContent(/code-linking rate limit \(10 per hour\)/i);
  });

  it("shows a specific message on 422 claim_not_linkable_to_code", async () => {
    await renderPanel(CLOUD);
    vi.mocked(linkClaimToCode).mockRejectedValueOnce(
      new ApiRequestError(422, { code: "claim_not_linkable_to_code", message: "raw backend text" }),
    );
    await fillCloudAndFind("Uses multi-head attention.");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only method and reported-result claims can be linked to code.",
    );
  });

  it.each([
    ["repository_not_found", 404, /no longer linked to this paper/],
    ["claim_not_found", 404, /claim no longer exists/],
    ["github_repo_not_found", 404, /GitHub could not find that repository/],
    ["github_unavailable", 502, /GitHub could not be reached/],
  ])("shows a specific message for %s", async (code, status, expected) => {
    await renderPanel(CLOUD);
    vi.mocked(linkClaimToCode).mockRejectedValueOnce(new ApiRequestError(status, { code, message: "<b>raw</b>" }));
    await fillCloudAndFind("Uses multi-head attention.");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(expected);
    expect(alert).not.toHaveTextContent("raw");
  });

  it("flips the session indicator on dispatch even with a local provider (GitHub egress), not on selection", async () => {
    await renderPanel(LOCAL);
    vi.mocked(linkClaimToCode).mockResolvedValueOnce([]);
    const session = renderHook(() => useSessionMode());
    fireEvent.change(screen.getByLabelText("Endpoint"), { target: { value: "http://localhost:11434" } });
    expect(session.result.current).toBe("local");

    await screen.findByRole("option", { name: "Gemini Pro" });
    fireEvent.click(
      within(screen.getByText("Uses multi-head attention.").closest("li") as HTMLElement).getByRole("button", {
        name: "Find implementing code",
      }),
    );

    await waitFor(() => expect(linkClaimToCode).toHaveBeenCalled());
    expect(session.result.current).toBe("cloud");
  });

  it("prompts to link a repository when none exist", async () => {
    vi.mocked(getProviders).mockResolvedValueOnce([CLOUD]);
    vi.mocked(getRepositories).mockResolvedValueOnce([]);
    vi.mocked(getCodeLinks).mockResolvedValueOnce([]);
    render(<CodeLinksPanel paperId="paper-1" claims={CLAIMS} />);

    expect(await screen.findByText("Link a repository above to find code for a claim.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Find implementing code" })).not.toBeInTheDocument();
  });
});
