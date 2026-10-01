/**
 * Session-wide (not per-panel) local/"cloud" indicator state. "cloud" means
 * "something left this machine": either a cloud AI provider was used
 * (markProviderUsed) or a backend feature called an external service
 * regardless of the AI provider chosen — arXiv, OpenAlex, GitHub
 * (markExternalDataSent). Tracks actual *dispatched* requests, never
 * dropdown selection — picking a cloud provider without submitting sends
 * nothing anywhere. Module-level state, not React state: readable/writable from
 * independent panels across routes that never mount simultaneously.
 *
 * In-memory only, resets on page reload — same "never persist" ethos as
 * credentials (see docs/SECURITY.md). Monotonic: once a cloud provider is
 * used or external data is sent, state stays "cloud" for the session; it never flips back to "local"
 * until a reload re-initializes this module.
 *
 * useSyncExternalStore subscribe/getSnapshot idiom mirrors the one already
 * established in components/neural-map.tsx for prefers-reduced-motion.
 */

import { useSyncExternalStore } from "react";
import type { ProviderCatalogEntry } from "./provider-types";

export type SessionMode = "local" | "cloud";

let dataLeftMachineThisSession = false;
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function getSnapshot(): SessionMode {
  return dataLeftMachineThisSession ? "cloud" : "local";
}

/** Call at the exact point a real request is dispatched with this provider —
 * never on provider-picker `onChange`. A local (`auth === "none"`) provider
 * is a no-op. */
export function markProviderUsed(provider: ProviderCatalogEntry): void {
  if (provider.auth !== "api_key") return;
  markExternalDataSent();
}

/** Call at the exact dispatch point of any request whose backend handler
 * calls an external service (arXiv, OpenAlex, GitHub) — independent of which
 * AI provider is selected, since a local model does not stop those calls. */
export function markExternalDataSent(): void {
  if (dataLeftMachineThisSession) return;
  dataLeftMachineThisSession = true;
  for (const listener of listeners) listener();
}

export function useSessionMode(): SessionMode {
  return useSyncExternalStore(subscribe, getSnapshot, () => "local");
}

// ponytail: test-only escape hatch, not exported from the public module
// surface — resets the module singleton between test cases since there's no
// real page reload in a test runner.
export function __resetSessionModeForTests(): void {
  dataLeftMachineThisSession = false;
}
