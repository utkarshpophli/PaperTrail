"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ProviderPicker } from "@/components/provider-picker";
import { ApiRequestError } from "@/lib/api-types";
import { isSelectionReady, toStageConfig, useProviderSelection } from "@/lib/provider-selection-store";
import { markProviderUsed } from "@/lib/session-mode-store";
import { streamAnalysis, type AnalysisEvent, type AnalysisStage } from "@/lib/evidence-api";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Analysis failed.";
}

const STAGE_OPTIONS: { stage: AnalysisStage; label: string }[] = [
  { stage: "evidence", label: "Evidence (claims, metrics, glossary)" },
  { stage: "technical", label: "Technical appendix" },
  { stage: "report", label: "Deep report" },
  { stage: "visual", label: "Story + Learning Layer" },
];

type AnalyzeState =
  | { phase: "idle" }
  | { phase: "streaming"; log: string[]; currentStage: string | null }
  | { phase: "error"; message: string; rateLimited: boolean }
  | { phase: "done" };

function describeEvent(event: AnalysisEvent): string {
  if (event.type === "progress") return event.message ?? event.stage ?? "Working…";
  if (event.type === "checkpoint") {
    const counts = event.data ? Object.entries(event.data).map(([k, v]) => `${v} ${k}`).join(", ") : "";
    return `${event.stage ?? "checkpoint"}: ${counts}`;
  }
  return event.message ?? event.type;
}

interface AnalyzePanelProps {
  paperId: string;
  /** Called once a "done" event arrives, so the parent can (re)fetch evidence. */
  onAnalysisDone: () => void;
}

// Provider/credential/model come from the shared in-memory selection
// (lib/provider-selection-store.ts) — the credential is never persisted.
export function AnalyzePanel({ paperId, onAnalysisDone }: AnalyzePanelProps) {
  const [selectedStages, setSelectedStages] = useState<Set<AnalysisStage>>(new Set<AnalysisStage>(["evidence"]));
  const [state, setState] = useState<AnalyzeState>({ phase: "idle" });

  function toggleStage(stage: AnalysisStage): void {
    setSelectedStages((current) => {
      const next = new Set(current);
      if (next.has(stage)) next.delete(stage);
      else next.add(stage);
      return next;
    });
  }

  const selection = useProviderSelection();
  const selectedProvider = selection.provider;
  const isStreaming = state.phase === "streaming";

  async function handleAnalyze(): Promise<void> {
    if (!selectedProvider) return;
    setState({ phase: "streaming", log: [], currentStage: null });
    const stageConfig = toStageConfig(selection);
    // One provider/credential applied to every selected stage — per-stage
    // distinct providers can wait until a phase that needs them.
    const stages = Object.fromEntries(Array.from(selectedStages).map((stage) => [stage, stageConfig]));
    markProviderUsed(selectedProvider);
    try {
      await streamAnalysis(
        paperId,
        { stages },
        (event) => {
          if (event.type === "error") {
            setState({ phase: "error", message: event.message ?? "Analysis failed.", rateLimited: false });
            return;
          }
          if (event.type === "done") {
            setState({ phase: "done" });
            onAnalysisDone();
            return;
          }
          setState((prev) => ({
            phase: "streaming",
            log: [...(prev.phase === "streaming" ? prev.log : []), describeEvent(event)],
            currentStage: event.stage,
          }));
        },
      );
    } catch (error: unknown) {
      const rateLimited = error instanceof ApiRequestError && error.status === 429;
      setState({ phase: "error", message: errorMessage(error), rateLimited });
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Analyze</h2>

      <fieldset className="flex flex-wrap items-center gap-4" disabled={isStreaming}>
        <legend className="sr-only">Stages to run</legend>
        {STAGE_OPTIONS.map(({ stage, label }) => (
          <label key={stage} className="flex items-center gap-1.5 text-ui-label text-foreground">
            <input type="checkbox" checked={selectedStages.has(stage)} onChange={() => toggleStage(stage)} />
            {label}
          </label>
        ))}
      </fieldset>

      <ProviderPicker disabled={isStreaming} />

      <div>
        <Button
          type="button"
          onClick={() => void handleAnalyze()}
          disabled={!isSelectionReady(selection) || isStreaming || selectedStages.size === 0}
        >
          {isStreaming ? "Analyzing…" : "Analyze"}
        </Button>
      </div>

      {state.phase === "streaming" && (
        <div className="flex flex-col gap-1">
          {state.currentStage && (
            <p className="text-ui-label font-medium text-foreground">Running: {state.currentStage}</p>
          )}
          <ul className="flex flex-col gap-1 text-ui-label text-muted-foreground" aria-live="polite">
            {state.log.map((line, index) => (
              // ponytail: index key is fine here, this list is append-only and never reordered
              <li key={index}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {state.phase === "error" && (
        <p role="alert" className="rounded-md bg-mismatch-bg px-3 py-2 text-body text-mismatch">
          {state.rateLimited
            ? `You've hit the analysis rate limit (5 per hour). Try again later. (${state.message})`
            : state.message}
        </p>
      )}

      {state.phase === "done" && <p className="text-body text-verified">Analysis complete.</p>}
    </div>
  );
}
