/**
 * Session-wide provider/credential/model selection shared by every panel that
 * calls a model, so a user enters a key once and it survives navigation
 * between pages. Module-level state read through useSyncExternalStore, same
 * idiom as lib/session-mode-store.ts.
 *
 * In-memory only: the credential is NEVER written to localStorage,
 * sessionStorage, cookies or the URL and is lost on a full page reload
 * (docs/SECURITY.md). It is sent to the backend per request, nothing else.
 *
 * A "slot" is an independent selection (the default slot backs every normal
 * picker; the composer's per-stage disclosure uses one slot per stage).
 */

import { useSyncExternalStore } from "react";
import type { StageConfig } from "./evidence-api";
import type { ProviderCatalogEntry } from "./provider-types";

export interface ProviderSelection {
  provider: ProviderCatalogEntry | null;
  /** API key when provider.auth === "api_key", endpoint URL when "none". */
  credential: string;
  model: string;
  /** Separate model id for features that also need an embedding call
   * (Graph, Discover recommendations/landscape, Roadmap create) — a chat
   * model and an embedding model are never the same id, and a chat-only
   * provider (Anthropic, Groq) has no valid value for this at all. */
  embedModel: string;
}

export const DEFAULT_SLOT = "default";

const EMPTY_SELECTION: ProviderSelection = { provider: null, credential: "", model: "", embedModel: "" };

/** Loopback defaults (the backend only accepts loopback endpoints for local
 * providers, and accepts these with or without a trailing /v1). */
const DEFAULT_ENDPOINTS: Record<string, string> = {
  ollama: "http://localhost:11434",
  lmstudio: "http://localhost:1234",
  llama_cpp: "http://localhost:8080",
};
const FALLBACK_ENDPOINT = "http://localhost:11434";

export function defaultEndpointFor(providerId: string): string {
  return DEFAULT_ENDPOINTS[providerId] ?? FALLBACK_ENDPOINT;
}

let slots: ReadonlyMap<string, ProviderSelection> = new Map();
// Remembers each provider's credential within a slot so switching away and
// back doesn't lose what was typed. Same in-memory-only rule.
const credentialMemory = new Map<string, string>();
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function write(slot: string, next: ProviderSelection): void {
  const copy = new Map(slots);
  copy.set(slot, next);
  slots = copy;
  for (const listener of listeners) listener();
}

export function getProviderSelection(slot: string = DEFAULT_SLOT): ProviderSelection {
  return read(slot);
}

function read(slot: string): ProviderSelection {
  return slots.get(slot) ?? EMPTY_SELECTION;
}

/** Choosing a provider resets the model (model ids are provider-specific) and
 * restores that provider's remembered credential, or the default endpoint for
 * local providers. Re-selecting the same provider is a no-op apart from
 * refreshing its catalog entry. */
export function selectProvider(slot: string, provider: ProviderCatalogEntry): void {
  const current = read(slot);
  if (current.provider?.id === provider.id) {
    if (current.provider !== provider) write(slot, { ...current, provider });
    return;
  }
  const remembered = credentialMemory.get(`${slot}:${provider.id}`);
  const credential = remembered ?? (provider.auth === "none" ? defaultEndpointFor(provider.id) : "");
  write(slot, { provider, credential, model: "", embedModel: "" });
}

export function setCredential(slot: string, credential: string): void {
  const current = read(slot);
  if (current.provider) credentialMemory.set(`${slot}:${current.provider.id}`, credential);
  write(slot, { ...current, credential });
}

export function setModel(slot: string, model: string): void {
  write(slot, { ...read(slot), model });
}

export function setEmbedModel(slot: string, embedModel: string): void {
  write(slot, { ...read(slot), embedModel });
}

export function useProviderSelection(slot: string = DEFAULT_SLOT): ProviderSelection {
  return useSyncExternalStore(
    subscribe,
    () => read(slot),
    () => EMPTY_SELECTION,
  );
}

export interface SelectionNeeds {
  /** @default true */
  chat?: boolean;
  /** @default false */
  embed?: boolean;
}

/** True when a request can be dispatched: a provider, a non-blank
 * credential, and a non-blank model for each capability the feature needs.
 * No field ever falls back to a hard-coded default -- an empty model blocks
 * the request rather than letting the backend guess. */
export function isSelectionReady(selection: ProviderSelection, needs: SelectionNeeds = {}): boolean {
  const { chat = true, embed = false } = needs;
  if (selection.provider === null || selection.credential.trim() === "") return false;
  if (chat && selection.model.trim() === "") return false;
  if (embed && selection.embedModel.trim() === "") return false;
  return true;
}

/** The per-stage request shape: exactly one of api_key/endpoint, plus
 * `model` (and `embed_model` when the feature needs one) -- both always
 * sent, never silently omitted for the backend to guess. Throws if a
 * required field is blank; callers gate dispatch on `isSelectionReady`
 * first, so this never fires in practice. */
export function toStageConfig(selection: ProviderSelection, needs: SelectionNeeds = {}): StageConfig {
  const { chat = true, embed = false } = needs;
  if (!isSelectionReady(selection, needs)) throw new Error("Provider selection is not ready to dispatch.");
  const provider = selection.provider as ProviderCatalogEntry;
  const credential = selection.credential.trim();
  return {
    provider_id: provider.id,
    ...(provider.auth === "api_key" ? { api_key: credential } : { endpoint: credential }),
    ...(chat ? { model: selection.model.trim() } : {}),
    ...(embed ? { embed_model: selection.embedModel.trim() } : {}),
  };
}

// ponytail: test-only reset, same rationale as session-mode-store's.
export function __resetProviderSelectionForTests(): void {
  slots = new Map();
  credentialMemory.clear();
  for (const listener of listeners) listener();
}
