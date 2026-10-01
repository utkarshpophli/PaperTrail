"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProviderPicker } from "@/components/provider-picker";
import { ClaimReferenceList } from "@/components/claim-reference-list";
import { ApiRequestError } from "@/lib/api-types";
import { isSelectionReady, toStageConfig, useProviderSelection } from "@/lib/provider-selection-store";
import { markProviderUsed } from "@/lib/session-mode-store";
import { getPapers } from "@/lib/papers-api";
import type { PaperResponse } from "@/lib/paper-types";
import {
  getClaim,
  streamAssistant,
  type AnalysisEvent,
  type AssistantAction,
  type AssistantResponse,
  type ClaimResponse,
} from "@/lib/evidence-api";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Assistant request failed.";
}

const ACTION_OPTIONS: { action: AssistantAction; label: string }[] = [
  { action: "understand", label: "Understand" },
  { action: "deep-dive", label: "Deep dive" },
  { action: "challenge", label: "Challenge" },
  { action: "compare", label: "Compare with other papers" },
  { action: "verify", label: "Verify a claim" },
  { action: "implement", label: "Implementation guidance" },
  { action: "research", label: "Related research" },
  { action: "learn", label: "Learn" },
];

type AssistantState =
  | { phase: "idle" }
  | { phase: "streaming"; log: string[] }
  | { phase: "error"; message: string; rateLimited: boolean }
  | { phase: "done"; answer: string; claims: ClaimResponse[] };

function describeEvent(event: AnalysisEvent): string {
  if (event.type === "progress") return event.message ?? event.stage ?? "Working…";
  return event.message ?? event.type;
}

function parseAssistantResponse(data: Record<string, unknown> | null): AssistantResponse | null {
  if (!data) return null;
  const { answer, claim_ids: claimIds } = data;
  if (typeof answer !== "string" || !Array.isArray(claimIds)) return null;
  if (!claimIds.every((id): id is string => typeof id === "string")) return null;
  return { answer, claim_ids: claimIds };
}

/**
 * Resolves one cited claim id against the primary paper first, then (for
 * `compare`) each compared-against paper in turn -- the assistant's
 * `claim_ids` aren't tagged with which paper they belong to, and a `compare`
 * answer can cite claims that live on any of the involved papers. Returns
 * `null` (dropped by the caller) if no paper in the set owns it, same
 * "sources unavailable" fallback ClaimReferenceList already renders for an
 * unresolved id.
 */
async function resolveCitedClaim(
  paperIds: readonly string[],
  claimId: string,
): Promise<ClaimResponse | null> {
  for (const paperId of paperIds) {
    try {
      return await getClaim(paperId, claimId);
    } catch (error: unknown) {
      if (error instanceof ApiRequestError && error.code === "claim_not_found") continue;
      throw error;
    }
  }
  return null;
}

interface AssistantPanelProps {
  paperId: string;
}

// Provider/credential/model come from the shared in-memory selection
// (lib/provider-selection-store.ts) — the credential is never persisted.
export function AssistantPanel({ paperId }: AssistantPanelProps) {
  const [action, setAction] = useState<AssistantAction>("understand");
  const [question, setQuestion] = useState("");
  const [otherPapers, setOtherPapers] = useState<PaperResponse[]>([]);
  const [otherPapersError, setOtherPapersError] = useState<string | null>(null);
  const [comparePaperIds, setComparePaperIds] = useState<Set<string>>(new Set());
  const [state, setState] = useState<AssistantState>({ phase: "idle" });

  const selection = useProviderSelection();

  useEffect(() => {
    if (action !== "compare") return;
    getPapers()
      .then((papers) => setOtherPapers(papers.filter((paper) => paper.id !== paperId)))
      .catch((error: unknown) => setOtherPapersError(errorMessage(error)));
  }, [action, paperId]);

  function toggleComparePaper(id: string): void {
    setComparePaperIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const selectedProvider = selection.provider;
  const isStreaming = state.phase === "streaming";
  const needsCompareSelection = action === "compare" && comparePaperIds.size === 0;

  async function handleAsk(): Promise<void> {
    if (!selectedProvider || needsCompareSelection) return;
    setState({ phase: "streaming", log: [] });
    // A plain mutable holder, not a reassigned `let`: TS's control-flow
    // narrowing doesn't track reassignment of an outer `let` from inside a
    // callback passed to another function, so `result` would still type as
    // `null` after the try/await below. A property read is re-evaluated
    // fresh each access instead.
    const resultHolder: { current: AssistantResponse | null } = { current: null };
    const comparePaperIdList = Array.from(comparePaperIds);

    markProviderUsed(selectedProvider);
    try {
      await streamAssistant(
        paperId,
        {
          action,
          ...(question.trim() ? { question: question.trim() } : {}),
          ...(action === "compare" ? { compare_with: comparePaperIdList } : {}),
          ...toStageConfig(selection),
        },
        (event) => {
          if (event.type === "error") {
            setState({ phase: "error", message: event.message ?? "Assistant request failed.", rateLimited: false });
            return;
          }
          if (event.type === "done") {
            resultHolder.current = parseAssistantResponse(event.data);
            return;
          }
          setState((prev) => ({
            phase: "streaming",
            log: [...(prev.phase === "streaming" ? prev.log : []), describeEvent(event)],
          }));
        },
      );
    } catch (error: unknown) {
      const rateLimited = error instanceof ApiRequestError && error.status === 429;
      setState({ phase: "error", message: errorMessage(error), rateLimited });
      return;
    }

    const result = resultHolder.current;
    if (result === null) return; // an error event already set the error state above

    const searchablePaperIds = [paperId, ...comparePaperIdList];
    const claims = await Promise.all(
      result.claim_ids.map((claimId) => resolveCitedClaim(searchablePaperIds, claimId)),
    );
    setState({
      phase: "done",
      answer: result.answer,
      claims: claims.filter((claim): claim is ClaimResponse => claim !== null),
    });
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Research Assistant</h2>

      <label className="flex flex-col gap-1 text-ui-label text-foreground" htmlFor="assistant-action">
        Action
        <select
          id="assistant-action"
          value={action}
          onChange={(event) => setAction(event.target.value as AssistantAction)}
          disabled={isStreaming}
          className="rounded-md border border-input bg-background px-2 py-1.5 text-body text-foreground"
        >
          {ACTION_OPTIONS.map(({ action: value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-ui-label text-foreground" htmlFor="assistant-question">
        Question (optional)
        <textarea
          id="assistant-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={isStreaming}
          rows={3}
          className="rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
        />
      </label>

      {action === "compare" && (
        <fieldset className="flex flex-col gap-1.5" disabled={isStreaming}>
          <legend className="text-ui-label text-foreground">Compare with</legend>
          {otherPapersError && (
            <p role="alert" className="text-body text-mismatch">
              {otherPapersError}
            </p>
          )}
          {!otherPapersError && otherPapers.length === 0 && (
            <p className="text-caption text-muted-foreground">No other papers available to compare against.</p>
          )}
          {otherPapers.map((paper) => (
            <label key={paper.id} className="flex items-center gap-1.5 text-ui-label text-foreground">
              <input
                type="checkbox"
                checked={comparePaperIds.has(paper.id)}
                onChange={() => toggleComparePaper(paper.id)}
              />
              {paper.title}
            </label>
          ))}
          {needsCompareSelection && (
            <p className="text-caption text-muted-foreground">Select at least one paper to compare against.</p>
          )}
        </fieldset>
      )}

      <ProviderPicker disabled={isStreaming} />

      <div>
        <Button
          type="button"
          onClick={() => void handleAsk()}
          disabled={!isSelectionReady(selection) || isStreaming || needsCompareSelection}
        >
          {isStreaming ? "Asking…" : "Ask"}
        </Button>
      </div>

      {state.phase === "streaming" && (
        <ul className="flex flex-col gap-1 text-ui-label text-muted-foreground" aria-live="polite">
          {state.log.map((line, index) => (
            // ponytail: index key is fine here, this list is append-only and never reordered
            <li key={index}>{line}</li>
          ))}
        </ul>
      )}

      {state.phase === "error" && (
        <p role="alert" className="rounded-md bg-mismatch-bg px-3 py-2 text-body text-mismatch">
          {state.rateLimited
            ? `You've hit the assistant rate limit (30 per hour). Try again later. (${state.message})`
            : state.message}
        </p>
      )}

      {state.phase === "done" && (
        <div className="flex flex-col gap-2">
          <p className="whitespace-pre-wrap text-body text-foreground">{state.answer}</p>
          <div className="flex flex-col gap-1">
            <p className="text-caption font-medium text-muted-foreground">Sources</p>
            <ClaimReferenceList claimIds={state.claims.map((claim) => claim.id)} claims={state.claims} />
          </div>
        </div>
      )}
    </div>
  );
}
