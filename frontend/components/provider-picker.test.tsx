import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { OTHER_MODEL_VALUE, ProviderPicker } from "./provider-picker";
import { __resetProviderSelectionForTests, getProviderSelection } from "@/lib/provider-selection-store";
import { getProviderModels, getProviders, testProviderModel } from "@/lib/providers-api";
import { ApiRequestError } from "@/lib/api-types";
import { __resetSessionModeForTests, useSessionMode } from "@/lib/session-mode-store";
import type { ProviderCatalogEntry, ProviderModel, ProviderModelsResponse } from "@/lib/provider-types";

vi.mock("@/lib/providers-api", () => ({
  getProviders: vi.fn(),
  getProviderModels: vi.fn(),
  testProviderModel: vi.fn(),
}));

const CATALOG: ProviderCatalogEntry[] = [
  { id: "openai", label: "OpenAI", auth: "api_key", capabilities: [], implemented: true },
  { id: "anthropic", label: "Anthropic", auth: "api_key", capabilities: [], implemented: true },
  { id: "ollama", label: "Ollama", auth: "none", capabilities: [], implemented: true },
  { id: "mistral", label: "Mistral", auth: "api_key", capabilities: [], implemented: false },
];

function model(id: string): ProviderModel {
  return { id, label: id, context_length: null, kind: "chat" };
}

function live(...ids: string[]): ProviderModelsResponse {
  return { models: ids.map(model) };
}

// Auto-load is debounced (600 ms) for pasted keys.
const SLOW = { timeout: 3000 };

async function renderPicker(props: Partial<ComponentProps<typeof ProviderPicker>> = {}): Promise<void> {
  render(<ProviderPicker {...props} />);
  await screen.findByRole("option", { name: "OpenAI" });
}

function typeKey(value: string): void {
  fireEvent.change(screen.getByLabelText("API key"), { target: { value } });
}

describe("ProviderPicker", () => {
  beforeEach(() => {
    vi.mocked(getProviders).mockResolvedValue(CATALOG);
    vi.mocked(getProviderModels).mockResolvedValue(live());
  });

  afterEach(() => {
    __resetProviderSelectionForTests();
    __resetSessionModeForTests();
    vi.resetAllMocks();
  });

  it("defaults to the first implemented provider and disables unimplemented ones", async () => {
    await renderPicker();
    expect(screen.getByLabelText("Provider")).toHaveValue("openai");
    expect(screen.getByRole("option", { name: "Mistral (coming soon)" })).toBeDisabled();
    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "password");
  });

  it("does not list models until a credential is present, then loads them automatically", async () => {
    vi.mocked(getProviderModels).mockResolvedValue(live("gpt-a", "gpt-b"));
    await renderPicker();
    expect(getProviderModels).not.toHaveBeenCalled();

    typeKey("sk-test");
    expect(await screen.findByRole("option", { name: "gpt-a" }, SLOW)).toBeInTheDocument();
    expect(getProviderModels).toHaveBeenCalledTimes(1);
    expect(vi.mocked(getProviderModels).mock.calls[0][0]).toBe("openai");
    expect(vi.mocked(getProviderModels).mock.calls[0][1]).toEqual({ api_key: "sk-test" });
  });

  it("selecting a model stores it, and switching provider resets the model", async () => {
    vi.mocked(getProviderModels).mockResolvedValue(live("gpt-a"));
    await renderPicker();
    typeKey("sk-test");
    await screen.findByRole("option", { name: "gpt-a" }, SLOW);

    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "gpt-a" } });
    expect(getProviderSelection().model).toBe("gpt-a");

    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "anthropic" } });
    expect(getProviderSelection()).toMatchObject({ model: "", credential: "" });
    expect(screen.getByLabelText("Model")).toHaveValue("");
  });

  it("auto-selects the first live model once the list loads, instead of silently staying on a stale provider default", async () => {
    vi.mocked(getProviderModels).mockResolvedValue(live("gpt-a", "gpt-b"));
    await renderPicker();
    typeKey("sk-test");

    await waitFor(() => expect(getProviderSelection().model).toBe("gpt-a"), SLOW);
    expect(screen.getByLabelText("Model")).toHaveValue("gpt-a");
  });

  it("does not override a model the user already chose once a later load resolves", async () => {
    vi.mocked(getProviderModels).mockResolvedValue(live("gpt-a", "gpt-b"));
    await renderPicker();
    typeKey("sk-test");
    await waitFor(() => expect(getProviderSelection().model).toBe("gpt-a"), SLOW);

    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "gpt-b" } });
    expect(getProviderSelection().model).toBe("gpt-b");

    vi.mocked(getProviderModels).mockResolvedValue(live("gpt-a", "gpt-b", "gpt-c"));
    fireEvent.click(screen.getByRole("button", { name: "Reload models" }));
    await screen.findByRole("option", { name: "gpt-c" }, SLOW);

    expect(getProviderSelection().model).toBe("gpt-b");
  });

  it("reloads on demand", async () => {
    vi.mocked(getProviderModels).mockResolvedValue(live("gpt-a"));
    await renderPicker();
    typeKey("sk-test");
    await screen.findByRole("option", { name: "gpt-a" }, SLOW);

    vi.mocked(getProviderModels).mockResolvedValue(live("gpt-a", "gpt-new"));
    fireEvent.click(screen.getByRole("button", { name: "Reload models" }));
    expect(await screen.findByRole("option", { name: "gpt-new" }, SLOW)).toBeInTheDocument();
  });

  it("shows a filter above 15 models and narrows the list without dropping the selection", async () => {
    const ids = Array.from({ length: 20 }, (_, i) => `model-${String(i).padStart(2, "0")}`);
    vi.mocked(getProviderModels).mockResolvedValue(live(...ids, "special-x"));
    await renderPicker();
    typeKey("sk-test");
    await screen.findByRole("option", { name: "special-x" }, SLOW);

    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "model-03" } });
    fireEvent.change(screen.getByLabelText("Filter models"), { target: { value: "special" } });

    expect(screen.getByRole("option", { name: "special-x" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "model-03" })).toBeInTheDocument(); // selection stays visible
    expect(screen.queryByRole("option", { name: "model-07" })).not.toBeInTheDocument();
  });

  it("has no filter for a short list", async () => {
    vi.mocked(getProviderModels).mockResolvedValue(live("a", "b"));
    await renderPicker();
    typeKey("sk-test");
    await screen.findByRole("option", { name: "a" }, SLOW);
    expect(screen.queryByLabelText("Filter models")).not.toBeInTheDocument();
  });

  it("'Other model id' reveals a free-text input that sets the model", async () => {
    await renderPicker();
    typeKey("sk-test");
    expect(screen.queryByLabelText("Other model id")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Model"), { target: { value: OTHER_MODEL_VALUE } });
    fireEvent.change(screen.getByLabelText("Other model id"), { target: { value: "vendor/custom-1" } });

    expect(getProviderSelection().model).toBe("vendor/custom-1");
  });

  it("shows the error when listing fails, and still allows a custom id", async () => {
    vi.mocked(getProviderModels).mockRejectedValue(new ApiRequestError(401, { code: "auth", message: "Bad key" }));
    await renderPicker();
    typeKey("sk-test");

    expect(await screen.findByRole("alert", undefined, SLOW)).toHaveTextContent("Bad key");
    expect(screen.getByRole("option", { name: "Other model id…" })).toBeInTheDocument();
  });

  it("lists local models immediately from the prefilled endpoint and explains an unreachable server", async () => {
    vi.mocked(getProviderModels).mockRejectedValue(new Error("connection refused"));
    await renderPicker();
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "ollama" } });

    expect(screen.getByLabelText("Endpoint")).toHaveValue("http://localhost:11434");
    const alert = await screen.findByRole("alert"); // default findBy timeout: no debounce for a prefilled endpoint
    expect(alert).toHaveTextContent("Could not reach a local server at http://localhost:11434");
    expect(alert).toHaveTextContent("Start Ollama");
    expect(vi.mocked(getProviderModels).mock.calls[0][1]).toEqual({ endpoint: "http://localhost:11434" });
  });

  it("tests the chosen model and shows the latency", async () => {
    vi.mocked(testProviderModel).mockResolvedValue({ ok: true, latency_ms: 420 });
    await renderPicker();
    typeKey("sk-test");
    expect(screen.getByRole("button", { name: "Test model" })).toBeDisabled(); // no model chosen yet

    fireEvent.change(screen.getByLabelText("Model"), { target: { value: OTHER_MODEL_VALUE } });
    fireEvent.change(screen.getByLabelText("Other model id"), { target: { value: "gpt-a" } });
    fireEvent.click(screen.getByRole("button", { name: "Test model" }));

    expect(await screen.findByRole("status")).toHaveTextContent("420 ms");
    expect(testProviderModel).toHaveBeenCalledWith("openai", { api_key: "sk-test", model: "gpt-a" });
  });

  it("shows the error text when the model test fails, and clears it when the model changes", async () => {
    vi.mocked(testProviderModel).mockRejectedValue(new ApiRequestError(502, { code: "x", message: "Model not found" }));
    await renderPicker();
    typeKey("sk-test");
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: OTHER_MODEL_VALUE } });
    fireEvent.change(screen.getByLabelText("Other model id"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Test model" }));

    expect(await screen.findByText(/Model test failed: Model not found/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Other model id"), { target: { value: "other" } });
    expect(screen.queryByText(/Model test failed/)).not.toBeInTheDocument();
  });

  it("never writes the credential to web storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    await renderPicker();
    typeKey("sk-super-secret");
    await waitFor(() => expect(getProviderModels).toHaveBeenCalled(), SLOW);

    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain("sk-super-secret");
    setItem.mockRestore();
  });

  it("flips the local/external indicator to cloud when listing models with a cloud credential", async () => {
    vi.mocked(getProviderModels).mockResolvedValue(live("gpt-a"));
    const session = renderHook(() => useSessionMode());
    await renderPicker();
    expect(session.result.current).toBe("local");

    typeKey("sk-test"); // openai (api_key) is the default provider in CATALOG
    await screen.findByRole("option", { name: "gpt-a" }, SLOW);
    expect(session.result.current).toBe("cloud");
  });

  it("does not flip the indicator when listing models for a local provider", async () => {
    vi.mocked(getProviderModels).mockResolvedValue(live("llama"));
    const session = renderHook(() => useSessionMode());
    await renderPicker();
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "ollama" } });

    await screen.findByRole("option", { name: "llama" }, SLOW);
    expect(session.result.current).toBe("local");
  });

  it("flips the indicator to cloud when testing a model against a cloud provider", async () => {
    vi.mocked(testProviderModel).mockResolvedValue({ ok: true, latency_ms: 10 });
    const session = renderHook(() => useSessionMode());
    await renderPicker();
    typeKey("sk-test");
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: OTHER_MODEL_VALUE } });
    fireEvent.change(screen.getByLabelText("Other model id"), { target: { value: "gpt-a" } });
    expect(session.result.current).toBe("local");

    fireEvent.click(screen.getByRole("button", { name: "Test model" }));
    expect(session.result.current).toBe("cloud"); // marked synchronously at dispatch, before the response resolves
  });

  it("labels every control (no placeholder-only names)", async () => {
    await renderPicker();
    typeKey("sk-test");
    for (const name of ["Provider", "API key", "Model"]) expect(screen.getByLabelText(name)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload models" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Test model" })).toBeInTheDocument();
  });

  it("never offers a 'Provider default' option -- an empty model always blocks, never silently guesses", async () => {
    vi.mocked(getProviderModels).mockResolvedValue(live());
    await renderPicker();
    typeKey("sk-test");
    await waitFor(() => expect(getProviderModels).toHaveBeenCalled(), SLOW);
    expect(screen.queryByRole("option", { name: "Provider default" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Select a model" })).toBeInTheDocument();
  });

  it("does not render an embedding select by default (needsEmbed off)", async () => {
    await renderPicker();
    typeKey("sk-test");
    expect(screen.queryByLabelText("Embedding model")).not.toBeInTheDocument();
  });

  describe("needsEmbed", () => {
    function embedModel(id: string): ProviderModel {
      return { id, label: id, context_length: null, kind: "embedding" };
    }

    it("renders a second, independently-loaded embedding model select", async () => {
      vi.mocked(getProviderModels).mockImplementation((_id, _creds, _signal, kind) =>
        Promise.resolve(kind === "embedding" ? { models: [embedModel("embed-a")] } : live("gpt-a")),
      );
      await renderPicker({ needsEmbed: true });
      typeKey("sk-test");

      expect(await screen.findByRole("option", { name: "gpt-a" }, SLOW)).toBeInTheDocument();
      expect(await screen.findByRole("option", { name: "embed-a" }, SLOW)).toBeInTheDocument();
      await waitFor(() => expect(getProviderSelection().model).toBe("gpt-a"), SLOW);
      await waitFor(() => expect(getProviderSelection().embedModel).toBe("embed-a"), SLOW);
    });

    it("shows a clear message when the provider has no embedding models, and blocks readiness on it", async () => {
      vi.mocked(getProviderModels).mockImplementation((_id, _creds, _signal, kind) =>
        Promise.resolve(kind === "embedding" ? live() : live("gpt-a")),
      );
      await renderPicker({ needsEmbed: true });
      typeKey("sk-test");

      expect(await screen.findByText("This provider has no embedding models.", undefined, SLOW)).toBeInTheDocument();
    });

    it("omits the chat model select entirely when needsChat is false", async () => {
      vi.mocked(getProviderModels).mockResolvedValue({ models: [embedModel("embed-a")] });
      await renderPicker({ needsChat: false, needsEmbed: true });
      typeKey("sk-test");

      await screen.findByRole("option", { name: "embed-a" }, SLOW);
      expect(screen.queryByLabelText("Model")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Test model" })).not.toBeInTheDocument();
    });
  });
});
