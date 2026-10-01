"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api-types";
import {
  DEFAULT_SLOT,
  getProviderSelection,
  selectProvider,
  setCredential,
  setEmbedModel,
  setModel,
  useProviderSelection,
} from "@/lib/provider-selection-store";
import { getProviders, testProviderModel } from "@/lib/providers-api";
import type { ProviderCatalogEntry } from "@/lib/provider-types";
import { markProviderUsed } from "@/lib/session-mode-store";
import { useProviderModels, type ModelsState } from "@/lib/use-provider-models";

/** Above this many models a text filter appears above the model select. */
const FILTER_THRESHOLD = 15;
/** Value of the "Other model id…" option; also lets tests choose it. */
export const OTHER_MODEL_VALUE = "__other__";
const NO_MODELS: never[] = [];

const FIELD = "rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground disabled:opacity-60";
const LABEL = "flex flex-col gap-1 text-ui-label font-medium text-foreground";

type TestState =
  | { status: "idle" }
  | { status: "testing" }
  | { status: "ok"; latencyMs: number }
  | { status: "error"; message: string };

/** A model select for one capability (chat or embedding): its own list,
 * filter, "other id" override, and status messages. Auto-selects the first
 * live model once a fresh list loads -- a hard-coded provider default drifts
 * out of date as models retire (confirmed live: NVIDIA NIM's own default
 * started 410-ing), so once a real list exists nothing here falls back to a
 * guess instead. */
function ModelField({
  idPrefix,
  label,
  models,
  value,
  onChange,
  disabled,
  emptyMessage,
  isLocal,
  providerLabel,
  credential,
}: {
  idPrefix: string;
  label: string;
  models: ModelsState;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  emptyMessage: string;
  isLocal: boolean;
  providerLabel: string;
  credential: string;
}) {
  const [filter, setFilter] = useState("");
  const [otherChosen, setOtherChosen] = useState(false);
  const listed = models.status === "loaded" ? models.models : NO_MODELS;

  const autoSelectedForRef = useRef<ModelsState | null>(null);
  useEffect(() => {
    if (models.status !== "loaded" || autoSelectedForRef.current === models) return;
    autoSelectedForRef.current = models;
    if (models.models.length > 0 && value === "" && !otherChosen) onChange(models.models[0].id);
  }, [models, value, otherChosen, onChange]);

  const knownModel = listed.some((entry) => entry.id === value);
  const showOtherInput = otherChosen || (value !== "" && !knownModel && models.status !== "loading");
  const visibleModels = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return listed;
    return listed.filter(
      (entry) =>
        entry.id === value || entry.id.toLowerCase().includes(needle) || entry.label.toLowerCase().includes(needle),
    );
  }, [listed, filter, value]);

  function handleSelectChange(next: string): void {
    if (next === OTHER_MODEL_VALUE) {
      setOtherChosen(true);
      onChange("");
      return;
    }
    setOtherChosen(false);
    onChange(next);
  }

  return (
    <div className="flex flex-col gap-2">
      {listed.length > FILTER_THRESHOLD && (
        <label className={LABEL} htmlFor={`${idPrefix}-filter`}>
          Filter {label.toLowerCase()}s
          <input
            id={`${idPrefix}-filter`}
            type="search"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder={`Search ${listed.length} models`}
            disabled={disabled}
            className={FIELD}
          />
        </label>
      )}

      <label className={LABEL} htmlFor={`${idPrefix}-model`}>
        {label}
        <select
          id={`${idPrefix}-model`}
          value={showOtherInput ? OTHER_MODEL_VALUE : value}
          onChange={(event) => handleSelectChange(event.target.value)}
          disabled={disabled}
          className={FIELD}
        >
          <option value="" disabled>
            {models.status === "loading" ? "Loading models…" : "Select a model"}
          </option>
          {visibleModels.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.label}
              {entry.context_length ? ` (${Math.round(entry.context_length / 1000)}k ctx)` : ""}
            </option>
          ))}
          <option value={OTHER_MODEL_VALUE}>Other model id…</option>
        </select>
      </label>

      {showOtherInput && (
        <label className={LABEL} htmlFor={`${idPrefix}-other`}>
          Other {label.toLowerCase()} id
          <input
            id={`${idPrefix}-other`}
            type="text"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder="Exact model id, e.g. provider/model-name"
            autoComplete="off"
            spellCheck={false}
            disabled={disabled}
            className={FIELD}
          />
        </label>
      )}

      <div aria-live="polite" className="flex flex-col gap-1">
        {models.status === "loading" && <p className="text-caption text-muted-foreground">Loading models…</p>}
        {models.status === "loaded" && models.models.length === 0 && (
          <p className="text-caption text-muted-foreground">{emptyMessage}</p>
        )}
        {models.status === "error" && (
          <p role="alert" className="rounded-md bg-mismatch-bg px-3 py-2 text-caption text-mismatch">
            {isLocal
              ? `Could not reach a local server at ${credential}. Start ${providerLabel} and check the endpoint, then reload. (${models.message})`
              : `Could not load models. Check the API key and reload, or type a model id. (${models.message})`}
          </p>
        )}
      </div>
    </div>
  );
}

export interface ProviderPickerProps {
  /** Independent selection to bind to; omit for the shared session selection. */
  slot?: string;
  /** Prefix for the group's accessible name, e.g. "Report stage". */
  label?: string;
  disabled?: boolean;
  /** Whether this feature calls the provider's chat model. @default true */
  needsChat?: boolean;
  /** Whether this feature also calls the provider's embedding model
   * (Graph, Discover recommendations/landscape, Roadmap create). When true,
   * a second model select appears, fed only by embedding-kind models --
   * empty for a chat-only provider (Anthropic, Groq), which naturally blocks
   * the feature rather than needing special-cased provider exclusion.
   * @default false */
  needsEmbed?: boolean;
}

/**
 * Provider -> credential -> model(s) -> "Test model". Reads and writes the
 * shared in-memory selection (lib/provider-selection-store.ts); the
 * credential is never persisted. Model ids come from the backend's live
 * listing, never a hard-coded list.
 */
export function ProviderPicker({
  slot = DEFAULT_SLOT,
  label,
  disabled = false,
  needsChat = true,
  needsEmbed = false,
}: ProviderPickerProps) {
  const uid = useId();
  const selection = useProviderSelection(slot);
  const { provider, credential, model, embedModel } = selection;
  const [catalog, setCatalog] = useState<ProviderCatalogEntry[]>([]);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [test, setTest] = useState<{ key: string; result: TestState } | null>(null);
  const { state: chatModels, reload: reloadChat } = useProviderModels(selection, "chat", needsChat);
  const { state: embedModels, reload: reloadEmbed } = useProviderModels(selection, "embedding", needsEmbed);

  useEffect(() => {
    let cancelled = false;
    getProviders()
      .then((entries) => {
        if (cancelled) return;
        setCatalog(entries);
        // Keep a selection that survived navigation (refreshing its catalog
        // entry); otherwise start on the first implemented provider.
        const currentId = getProviderSelection(slot).provider?.id;
        const initial =
          entries.find((entry) => entry.id === currentId && entry.implemented) ??
          entries.find((entry) => entry.implemented);
        if (initial) selectProvider(slot, initial);
      })
      .catch((error: unknown) => {
        if (!cancelled) setCatalogError(error instanceof Error ? error.message : "Could not load providers.");
      });
    return () => {
      cancelled = true;
    };
  }, [slot]);

  // A test result only applies to the exact provider/credential/model it ran with.
  const testKey = `${provider?.id}|${credential}|${model}`;
  const testState: TestState = test?.key === testKey ? test.result : { status: "idle" };

  function onProviderChange(id: string): void {
    const entry = catalog.find((candidate) => candidate.id === id);
    if (!entry) return;
    selectProvider(slot, entry);
  }

  async function onTest(): Promise<void> {
    if (!provider || !model.trim()) return;
    const key = testKey;
    setTest({ key, result: { status: "testing" } });
    // A test call to a cloud provider sends the key (and a ping prompt) off
    // this machine, same as any other real dispatch to that provider.
    markProviderUsed(provider);
    const creds = provider.auth === "api_key" ? { api_key: credential.trim() } : { endpoint: credential.trim() };
    try {
      const response = await testProviderModel(provider.id, { ...creds, model: model.trim() });
      setTest({ key, result: { status: "ok", latencyMs: response.latency_ms } });
    } catch (error: unknown) {
      const message = error instanceof ApiRequestError || error instanceof Error ? error.message : "Model test failed.";
      setTest({ key, result: { status: "error", message } });
    }
  }

  const isLocal = provider?.auth === "none";
  const groupName = label ? `${label} model` : "Model";

  return (
    <div role="group" aria-label={`${groupName} settings`} className="flex flex-col gap-3">
      {catalogError && (
        <p role="alert" className="text-body text-mismatch">
          {catalogError}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className={LABEL} htmlFor={`${uid}-provider`}>
          Provider
          <select
            id={`${uid}-provider`}
            value={provider?.id ?? ""}
            onChange={(event) => onProviderChange(event.target.value)}
            disabled={disabled}
            className={FIELD}
          >
            <option value="" disabled>
              Select a provider
            </option>
            {catalog.map((entry) => (
              <option key={entry.id} value={entry.id} disabled={!entry.implemented}>
                {entry.label}
                {entry.implemented ? "" : " (coming soon)"}
              </option>
            ))}
          </select>
        </label>

        {provider && (
          <label className={LABEL} htmlFor={`${uid}-credential`}>
            {isLocal ? "Endpoint" : "API key"}
            <input
              id={`${uid}-credential`}
              type={isLocal ? "text" : "password"}
              value={credential}
              onChange={(event) => setCredential(slot, event.target.value)}
              placeholder={isLocal ? "http://localhost:11434" : "Paste your API key"}
              autoComplete="off"
              spellCheck={false}
              disabled={disabled}
              className={FIELD}
            />
          </label>
        )}
      </div>

      {provider && needsChat && (
        <div className="flex flex-col gap-2">
          <ModelField
            key={provider.id}
            idPrefix={`${uid}-chat`}
            label="Model"
            models={chatModels}
            value={model}
            onChange={(value) => setModel(slot, value)}
            disabled={disabled}
            emptyMessage='No models were returned. Use "Other model id…" to type one.'
            isLocal={isLocal}
            providerLabel={provider.label}
            credential={credential.trim()}
          />
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={reloadChat}
              disabled={disabled || !credential.trim() || chatModels.status === "loading"}
            >
              Reload models
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void onTest()}
              disabled={disabled || !credential.trim() || !model.trim() || testState.status === "testing"}
            >
              {testState.status === "testing" ? "Testing…" : "Test model"}
            </Button>
          </div>

          <div aria-live="polite">
            {testState.status === "ok" && (
              <p role="status" className="text-caption font-medium text-verified">
                Model responded in {testState.latencyMs} ms.
              </p>
            )}
            {testState.status === "error" && (
              <p role="alert" className="rounded-md bg-mismatch-bg px-3 py-2 text-caption text-mismatch">
                Model test failed: {testState.message}
              </p>
            )}
          </div>
        </div>
      )}

      {provider && needsEmbed && (
        <div className="flex flex-col gap-2">
          <ModelField
            key={provider.id}
            idPrefix={`${uid}-embed`}
            label="Embedding model"
            models={embedModels}
            value={embedModel}
            onChange={(value) => setEmbedModel(slot, value)}
            disabled={disabled}
            emptyMessage="This provider has no embedding models."
            isLocal={isLocal}
            providerLabel={provider.label}
            credential={credential.trim()}
          />
          <div>
            <Button
              type="button"
              variant="outline"
              onClick={reloadEmbed}
              disabled={disabled || !credential.trim() || embedModels.status === "loading"}
            >
              Reload embedding models
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
