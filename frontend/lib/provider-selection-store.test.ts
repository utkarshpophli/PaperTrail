import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __resetProviderSelectionForTests,
  getProviderSelection,
  isSelectionReady,
  selectProvider,
  setCredential,
  setEmbedModel,
  setModel,
  toStageConfig,
} from "./provider-selection-store";
import type { ProviderCatalogEntry } from "./provider-types";

const CLOUD: ProviderCatalogEntry = { id: "openai", label: "OpenAI", auth: "api_key", capabilities: [], implemented: true };
const OTHER_CLOUD: ProviderCatalogEntry = { id: "anthropic", label: "Anthropic", auth: "api_key", capabilities: [], implemented: true };
const LOCAL: ProviderCatalogEntry = { id: "lmstudio", label: "LM Studio", auth: "none", capabilities: [], implemented: true };

describe("provider-selection-store", () => {
  afterEach(() => {
    __resetProviderSelectionForTests();
  });

  it("prefills the default loopback endpoint for a local provider", () => {
    selectProvider("default", LOCAL);
    expect(getProviderSelection().credential).toBe("http://localhost:1234");
  });

  it("resets model and embedModel on provider switch but remembers each provider's credential", () => {
    selectProvider("default", CLOUD);
    setCredential("default", "sk-openai");
    setModel("default", "gpt-x");
    setEmbedModel("default", "embed-x");

    selectProvider("default", OTHER_CLOUD);
    expect(getProviderSelection()).toMatchObject({ credential: "", model: "", embedModel: "" });
    setCredential("default", "sk-anthropic");

    selectProvider("default", CLOUD);
    expect(getProviderSelection()).toMatchObject({ credential: "sk-openai", model: "", embedModel: "" });
  });

  it("keeps slots independent", () => {
    selectProvider("default", CLOUD);
    setCredential("default", "a");
    selectProvider("stage-report", CLOUD);
    expect(getProviderSelection("stage-report").credential).toBe("");
    expect(getProviderSelection().credential).toBe("a");
  });

  it("builds a StageConfig with exactly one of api_key/endpoint, always including model -- never an empty/omitted default", () => {
    selectProvider("default", CLOUD);
    setCredential("default", "  sk-1  ");
    // Not ready yet -- no model chosen -- so building would silently omit a
    // required field. toStageConfig refuses rather than sending a partial config.
    expect(() => toStageConfig(getProviderSelection())).toThrow();

    setModel("default", "gpt-x");
    expect(toStageConfig(getProviderSelection())).toEqual({ provider_id: "openai", api_key: "sk-1", model: "gpt-x" });

    selectProvider("default", LOCAL);
    setModel("default", "llama-x");
    expect(toStageConfig(getProviderSelection())).toEqual({
      provider_id: "lmstudio",
      endpoint: "http://localhost:1234",
      model: "llama-x",
    });
  });

  it("also includes embed_model when the feature needs it, and omits model entirely for an embed-only feature", () => {
    selectProvider("default", CLOUD);
    setCredential("default", "sk-1");
    setModel("default", "gpt-x");
    setEmbedModel("default", "embed-x");

    expect(toStageConfig(getProviderSelection(), { embed: true })).toEqual({
      provider_id: "openai",
      api_key: "sk-1",
      model: "gpt-x",
      embed_model: "embed-x",
    });
    expect(toStageConfig(getProviderSelection(), { chat: false, embed: true })).toEqual({
      provider_id: "openai",
      api_key: "sk-1",
      embed_model: "embed-x",
    });
  });

  it("is ready only with a provider, a non-blank credential, and a model/embed_model for each capability needed", () => {
    expect(isSelectionReady(getProviderSelection())).toBe(false);
    selectProvider("default", CLOUD);
    expect(isSelectionReady(getProviderSelection())).toBe(false);
    setCredential("default", "   ");
    expect(isSelectionReady(getProviderSelection())).toBe(false);
    setCredential("default", "k");
    expect(isSelectionReady(getProviderSelection())).toBe(false); // no model yet -- chat defaults to required
    setModel("default", "gpt-x");
    expect(isSelectionReady(getProviderSelection())).toBe(true);

    expect(isSelectionReady(getProviderSelection(), { chat: false, embed: true })).toBe(false);
    setEmbedModel("default", "embed-x");
    expect(isSelectionReady(getProviderSelection(), { chat: false, embed: true })).toBe(true);
    expect(isSelectionReady(getProviderSelection(), { embed: true })).toBe(true); // chat AND embed both satisfied
  });

  it("never writes to web storage", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    selectProvider("default", CLOUD);
    setCredential("default", "sk-secret");
    setModel("default", "m");
    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    setItem.mockRestore();
  });
});
