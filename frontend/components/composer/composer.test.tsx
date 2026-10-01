import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { Composer } from "./composer";
import { getPaper, resolvePaperFromArxiv, uploadPaper } from "@/lib/papers-api";
import { getProviderModels, getProviders } from "@/lib/providers-api";
import { streamAnalysis, type AnalysisEvent } from "@/lib/evidence-api";
import { ApiRequestError } from "@/lib/api-types";
import { __resetProviderSelectionForTests } from "@/lib/provider-selection-store";
import { __resetSessionModeForTests, useSessionMode } from "@/lib/session-mode-store";
import type { PaperResponse } from "@/lib/paper-types";
import type { ProviderCatalogEntry } from "@/lib/provider-types";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/providers-api", () => ({
  getProviders: vi.fn(),
  getProviderModels: vi.fn().mockResolvedValue({ models: [] }),
  testProviderModel: vi.fn(),
}));
vi.mock("@/lib/papers-api", () => ({
  uploadPaper: vi.fn(),
  resolvePaperFromArxiv: vi.fn(),
  getPaper: vi.fn(),
  getPapers: vi.fn(),
}));
vi.mock("@/lib/evidence-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/evidence-api")>("@/lib/evidence-api");
  return { ...actual, streamAnalysis: vi.fn() };
});

const CLOUD: ProviderCatalogEntry = { id: "openai", label: "OpenAI", auth: "api_key", capabilities: [], implemented: true };
const CLOUD_2: ProviderCatalogEntry = { id: "anthropic", label: "Anthropic", auth: "api_key", capabilities: [], implemented: true };
const LOCAL: ProviderCatalogEntry = { id: "ollama", label: "Ollama", auth: "none", capabilities: [], implemented: true };

function paper(overrides: Partial<PaperResponse> = {}): PaperResponse {
  return {
    id: "p1",
    title: "Attention Is All You Need",
    authors: [],
    year: 2017,
    venue: null,
    doi: null,
    arxiv_id: "1706.03762",
    parse_status: "parsed",
    parse_error: null,
    created_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

function ev(type: AnalysisEvent["type"], stage: string | null, message: string | null = null, data: AnalysisEvent["data"] = null): AnalysisEvent {
  return { type, stage, message, data };
}

/** A well-behaved run: every stage reports progress then done. */
async function completeRun(_p: string, _r: unknown, onEvent: (e: AnalysisEvent) => void): Promise<void> {
  for (const stage of ["evidence", "technical", "report", "visual"]) {
    onEvent(ev("progress", stage, `Working on ${stage}`));
    onEvent(ev("done", stage));
  }
}

async function renderComposer(providers: ProviderCatalogEntry[] = [CLOUD]): Promise<void> {
  vi.mocked(getProviders).mockResolvedValue(providers);
  render(<Composer pollIntervalMs={5} />);
  await screen.findByRole("option", { name: providers[0].label });
}

const MODEL_ID = "gpt-a";

async function waitForModel(name: string = MODEL_ID): Promise<void> {
  await screen.findByRole("option", { name });
}

async function enterKey(value = "sk-test"): Promise<void> {
  fireEvent.change(screen.getByLabelText("API key"), { target: { value } });
  await waitForModel();
}

function chooseFile(name = "paper.pdf"): File {
  const file = new File(["%PDF-1.7"], name, { type: "application/pdf" });
  fireEvent.change(screen.getByLabelText(/Drop a PDF here/), { target: { files: [file] } });
  return file;
}

function typeSource(value: string): void {
  fireEvent.change(screen.getByLabelText("arXiv id, URL or title"), { target: { value } });
}

function generate(): void {
  fireEvent.click(screen.getByRole("button", { name: "Generate" }));
}

function stageRow(label: string): HTMLElement {
  const row = screen.getByText(label, { selector: "span" }).closest("li");
  if (!row) throw new Error(`no row for ${label}`);
  return row;
}

describe("Composer", () => {
  beforeEach(() => {
    vi.mocked(getProviderModels).mockResolvedValue({
      models: [{ id: MODEL_ID, label: MODEL_ID, context_length: null, kind: "chat" }],
    });
    vi.mocked(uploadPaper).mockResolvedValue(paper());
    vi.mocked(resolvePaperFromArxiv).mockResolvedValue(paper());
    vi.mocked(streamAnalysis).mockImplementation(completeRun);
  });

  afterEach(() => {
    __resetProviderSelectionForTests();
    __resetSessionModeForTests();
    vi.resetAllMocks();
    push.mockReset();
  });

  it("keeps Generate disabled until there is a paper, a credential, and a model", async () => {
    await renderComposer();
    expect(screen.getByRole("button", { name: "Generate" })).toBeDisabled();
    await enterKey();
    expect(screen.getByRole("button", { name: "Generate" })).toBeDisabled();
    chooseFile();
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate" })).toBeEnabled());
  });

  it("uploads a PDF, runs all four stages with one model, and opens the paper", async () => {
    await renderComposer();
    await enterKey("sk-test");
    const file = chooseFile();
    generate();

    await waitFor(() => expect(push).toHaveBeenCalledWith("/papers/p1"));
    expect(uploadPaper).toHaveBeenCalledWith(file);
    expect(resolvePaperFromArxiv).not.toHaveBeenCalled();

    const [paperId, request, , signal] = vi.mocked(streamAnalysis).mock.calls[0];
    expect(paperId).toBe("p1");
    expect(Object.keys(request.stages).sort()).toEqual(["evidence", "report", "technical", "visual"]);
    for (const config of Object.values(request.stages))
      expect(config).toEqual({ provider_id: "openai", api_key: "sk-test", model: MODEL_ID });
    expect(signal).toBeInstanceOf(AbortSignal);
  });

  it("extracts the id from an arXiv pdf URL instead of searching by title", async () => {
    await renderComposer();
    await enterKey();
    typeSource("https://arxiv.org/pdf/1706.03762");
    generate();

    await waitFor(() => expect(resolvePaperFromArxiv).toHaveBeenCalledWith({ arxivId: "1706.03762" }));
    await waitFor(() => expect(push).toHaveBeenCalled());
  });

  it("falls back to a title search for free text", async () => {
    await renderComposer();
    await enterKey();
    typeSource("Attention Is All You Need");
    generate();
    await waitFor(() => expect(resolvePaperFromArxiv).toHaveBeenCalledWith({ arxivTitle: "Attention Is All You Need" }));
  });

  it("keeps a local-model PDF run local", async () => {
    const session = renderHook(() => useSessionMode());
    await renderComposer([LOCAL]);
    await waitForModel();
    chooseFile();
    generate();
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(vi.mocked(streamAnalysis).mock.calls[0][1].stages.evidence).toEqual({
      provider_id: "ollama",
      endpoint: "http://localhost:11434",
      model: MODEL_ID,
    });
    expect(session.result.current).toBe("local");
  });

  it("marks the session external for an arXiv resolve even with a local model", async () => {
    const session = renderHook(() => useSessionMode());
    await renderComposer([LOCAL]);
    await waitForModel();
    typeSource("1706.03762");
    generate();
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(session.result.current).toBe("cloud");
  });

  it("marks the session external once a cloud provider is dispatched", async () => {
    const session = renderHook(() => useSessionMode());
    await renderComposer();
    expect(session.result.current).toBe("local"); // provider selected, but no credential sent anywhere yet
    await enterKey();
    chooseFile();
    generate();
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(session.result.current).toBe("cloud");
  });

  it("polls until the paper is parsed before analysing, showing parse status", async () => {
    vi.mocked(uploadPaper).mockResolvedValue(paper({ parse_status: "pending" }));
    vi.mocked(getPaper)
      .mockResolvedValueOnce(paper({ parse_status: "parsing" }))
      .mockResolvedValueOnce(paper({ parse_status: "parsed" }));
    await renderComposer();
    await enterKey();
    chooseFile();
    generate();

    expect(await screen.findByText("Parsing the PDF and extracting figures (on this machine)")).toBeInTheDocument();
    expect(streamAnalysis).not.toHaveBeenCalled();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/papers/p1"));
    expect(getPaper).toHaveBeenCalledTimes(2);
    expect(streamAnalysis).toHaveBeenCalledTimes(1);
  });

  it("surfaces a parse failure's exact error and never starts analysis", async () => {
    vi.mocked(uploadPaper).mockResolvedValue(paper({ parse_status: "pending" }));
    vi.mocked(getPaper).mockResolvedValue(paper({ parse_status: "failed", parse_error: "Encrypted PDF" }));
    await renderComposer();
    await enterKey();
    chooseFile();
    generate();

    expect(await screen.findByRole("alert")).toHaveTextContent("Encrypted PDF");
    expect(streamAnalysis).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("shows numbered stages moving waiting -> running -> done as events arrive", async () => {
    let release: () => void = () => {};
    vi.mocked(streamAnalysis).mockImplementation(async (_p, _r, onEvent) => {
      onEvent(ev("progress", "evidence", "Extracting claims"));
      onEvent(ev("done", "evidence"));
      onEvent(ev("progress", "technical", "Generating technical appendix"));
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      for (const stage of ["technical", "report", "visual"]) onEvent(ev("done", stage));
    });
    await renderComposer();
    await enterKey();
    chooseFile();
    generate();

    await waitFor(() => expect(within(stageRow("Technical")).getByText("Running")).toBeInTheDocument());
    expect(within(stageRow("Evidence")).getByText("Done")).toBeInTheDocument();
    expect(within(stageRow("Report")).getByText("Waiting")).toBeInTheDocument();
    expect(within(stageRow("Story")).getByText("Waiting")).toBeInTheDocument();
    expect(screen.getByText("Generating technical appendix")).toBeInTheDocument();
    expect(screen.getByText(/Elapsed 0:0\d/)).toBeInTheDocument();
    expect(screen.getByText(/Last activity \d+s ago/)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();

    release();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/papers/p1"));
  });

  it("cancels the in-flight run through the abort signal and closes the overlay", async () => {
    vi.mocked(streamAnalysis).mockImplementation(
      (_p, _r, _onEvent, signal) =>
        new Promise<void>((_resolve, reject) => {
          signal?.addEventListener("abort", () => reject(signal.reason));
        }),
    );
    await renderComposer();
    await enterKey();
    chooseFile();
    generate();

    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(vi.mocked(streamAnalysis).mock.calls[0][3]?.aborted).toBe(true);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Generate" })).toBeEnabled();
  });

  it("shows a stage error's exact text, marks the stage failed, and retries without re-uploading", async () => {
    vi.mocked(streamAnalysis).mockImplementationOnce(async (_p, _r, onEvent) => {
      onEvent(ev("progress", "evidence", "Extracting claims"));
      onEvent(ev("error", "evidence", "Provider timed out after 600 s"));
    });
    await renderComposer();
    await enterKey();
    chooseFile();
    generate();

    expect(await screen.findByRole("alert")).toHaveTextContent("Evidence: Provider timed out after 600 s");
    expect(within(stageRow("Evidence")).getByText("Failed")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/papers/p1"));
    expect(uploadPaper).toHaveBeenCalledTimes(1);
    expect(streamAnalysis).toHaveBeenCalledTimes(2);
  });

  it("shows a request failure's exact message", async () => {
    vi.mocked(streamAnalysis).mockRejectedValueOnce(
      new ApiRequestError(429, { code: "rate_limited", message: "Too many analyses, try later" }),
    );
    await renderComposer();
    await enterKey();
    chooseFile();
    generate();
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many analyses, try later");
  });

  it("treats a stream that ends before every stage finishes as an error", async () => {
    vi.mocked(streamAnalysis).mockImplementationOnce(async (_p, _r, onEvent) => {
      onEvent(ev("done", "evidence"));
    });
    await renderComposer();
    await enterKey();
    chooseFile();
    generate();
    expect(await screen.findByRole("alert")).toHaveTextContent("ended before every stage finished");
    expect(push).not.toHaveBeenCalled();
  });

  it("uses a stage's own model only once its picker is filled in, otherwise the main model", async () => {
    await renderComposer([CLOUD, CLOUD_2]);
    await enterKey("sk-main");
    chooseFile();
    fireEvent.click(screen.getByLabelText("Use a different model per stage"));

    const group = screen.getByRole("group", { name: "Report stage model settings" });
    await within(group).findByRole("option", { name: "Anthropic" });
    fireEvent.change(within(group).getByLabelText("Provider"), { target: { value: "anthropic" } });
    expect(within(group.parentElement as HTMLElement).getByText(/uses the main model/)).toBeInTheDocument();
    fireEvent.change(within(group).getByLabelText("API key"), { target: { value: "sk-report" } });
    await within(group).findByRole("option", { name: MODEL_ID });
    expect(within(group.parentElement as HTMLElement).getByText(/uses the model chosen here/)).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole("button", { name: "Generate" })).toBeEnabled());
    generate();
    await waitFor(() => expect(push).toHaveBeenCalled());
    const { stages } = vi.mocked(streamAnalysis).mock.calls[0][1];
    expect(stages.report).toEqual({ provider_id: "anthropic", api_key: "sk-report", model: MODEL_ID });
    expect(stages.evidence).toEqual({ provider_id: "openai", api_key: "sk-main", model: MODEL_ID });
    expect(stages.visual).toEqual({ provider_id: "openai", api_key: "sk-main", model: MODEL_ID });
  });

  it("rejects a non-PDF file", async () => {
    await renderComposer();
    const bad = new File(["x"], "notes.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText(/Drop a PDF here/), { target: { files: [bad] } });
    expect(screen.getByRole("alert")).toHaveTextContent("Only PDF files");
  });

  it("never persists the credential", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    await renderComposer();
    await enterKey("sk-do-not-store");
    chooseFile();
    generate();
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });
});
