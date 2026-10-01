import { useEffect, useState } from "react";
import { ApiRequestError } from "./api-types";
import { defaultEndpointFor, type ProviderSelection } from "./provider-selection-store";
import { getProviderModels } from "./providers-api";
import type { ModelKind, ProviderModel } from "./provider-types";
import { markProviderUsed } from "./session-mode-store";

export type ModelsState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; models: ProviderModel[] };

type Settled = Exclude<ModelsState, { status: "idle" | "loading" }>;

/** Wait after the last keystroke before listing models with a pasted key. */
const DEBOUNCE_MS = 600;

/**
 * Lists models for the current selection. Loads automatically once a
 * credential is present: immediately for a local provider still on its
 * prefilled default endpoint, debounced otherwise. Stale responses are
 * aborted. The result is keyed by the request it answers, so "idle"/"loading"
 * are derived rather than set synchronously inside the effect.
 */
export function useProviderModels(
  selection: ProviderSelection,
  kind: ModelKind = "chat",
  enabled: boolean = true,
): { state: ModelsState; reload: () => void } {
  const provider = selection.provider;
  const providerId = provider?.id ?? null;
  const auth = provider?.auth ?? null;
  const credential = selection.credential.trim();
  const [reloadCount, setReloadCount] = useState(0);
  const [settled, setSettled] = useState<{ key: string; result: Settled } | null>(null);

  const requestKey = enabled && providerId && credential ? `${providerId}|${credential}|${kind}|${reloadCount}` : null;

  useEffect(() => {
    if (!requestKey || !providerId || !auth) return;
    const controller = new AbortController();
    const immediate = auth === "none" && credential === defaultEndpointFor(providerId);
    const timer = setTimeout(
      () => {
        // Listing models with a cloud credential is a real request to that
        // cloud provider (the key leaves this machine), so it counts toward
        // the local/external session indicator same as any other dispatch.
        if (provider) markProviderUsed(provider);
        getProviderModels(
          providerId,
          auth === "api_key" ? { api_key: credential } : { endpoint: credential },
          controller.signal,
          kind,
        )
          .then((response) =>
            setSettled({ key: requestKey, result: { status: "loaded", models: response.models } }),
          )
          .catch((error: unknown) => {
            if (controller.signal.aborted) return;
            const message =
              error instanceof ApiRequestError || error instanceof Error ? error.message : "Could not list models.";
            setSettled({ key: requestKey, result: { status: "error", message } });
          });
      },
      immediate ? 0 : DEBOUNCE_MS,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // `provider` deliberately excluded: providerId/auth already cover every
    // change that should re-trigger this effect. Re-selecting the same
    // provider only refreshes its catalog entry (see provider-picker.tsx),
    // which must not re-fire a fetch or a duplicate markProviderUsed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey, providerId, auth, credential, kind]);

  const state: ModelsState =
    requestKey === null ? { status: "idle" } : settled?.key === requestKey ? settled.result : { status: "loading" };
  return { state, reload: () => setReloadCount((count) => count + 1) };
}
