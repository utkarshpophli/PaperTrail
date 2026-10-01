"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ProviderPicker } from "@/components/provider-picker";
import { ApiRequestError } from "@/lib/api-types";
import { isSelectionReady, toStageConfig, useProviderSelection } from "@/lib/provider-selection-store";
import { markExternalDataSent, markProviderUsed } from "@/lib/session-mode-store";
import { getPapers } from "@/lib/papers-api";
import type { PaperResponse } from "@/lib/paper-types";
import { streamRoadmap, parseRoadmap, type Roadmap, type RoadmapTarget } from "@/lib/discovery-api";
import type { AnalysisEvent } from "@/lib/evidence-api";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Roadmap generation failed.";
}

const ROADMAP_NEEDS = { chat: true, embed: true };

function describeEvent(event: AnalysisEvent): string {
  if (event.type === "progress") return event.message ?? event.stage ?? "Working…";
  return event.message ?? event.type;
}

type TargetType = RoadmapTarget["type"];

type FormState =
  | { phase: "idle" }
  | { phase: "streaming"; log: string[] }
  | { phase: "error"; message: string; rateLimited: boolean };

/** Roadmap creation form: topic-or-owned-paper target picker + the shared
 * provider picker (in-memory selection, credential never persisted). Streams `POST /discover/roadmap` and redirects to the
 * new roadmap's detail page on success. */
export function RoadmapCreateForm() {
  const router = useRouter();
  const [targetType, setTargetType] = useState<TargetType>("topic");
  const [topic, setTopic] = useState("");
  const [papers, setPapers] = useState<PaperResponse[]>([]);
  const [papersError, setPapersError] = useState<string | null>(null);
  const [paperId, setPaperId] = useState("");
  const [state, setState] = useState<FormState>({ phase: "idle" });

  const selection = useProviderSelection();

  useEffect(() => {
    getPapers()
      .then(setPapers)
      .catch((error: unknown) => setPapersError(errorMessage(error)));
  }, []);

  const selectedProvider = selection.provider;
  const isStreaming = state.phase === "streaming";
  const hasValidTarget = targetType === "topic" ? topic.trim().length > 0 : paperId.length > 0;

  async function handleCreate(): Promise<void> {
    if (!selectedProvider || !hasValidTarget) return;
    setState({ phase: "streaming", log: [] });
    const resultHolder: { current: Roadmap | null } = { current: null };

    const target: RoadmapTarget = targetType === "topic" ? { type: "topic", topic: topic.trim() } : { type: "paper", paper_id: paperId };

    markProviderUsed(selectedProvider);
    // Roadmap topic text also goes to arXiv search, whatever the AI provider.
    markExternalDataSent();
    try {
      await streamRoadmap(
        {
          target,
          ...toStageConfig(selection, ROADMAP_NEEDS),
        },
        (event) => {
          if (event.type === "error") {
            setState({ phase: "error", message: event.message ?? "Roadmap generation failed.", rateLimited: false });
            return;
          }
          if (event.type === "done") {
            resultHolder.current = parseRoadmap(event.data);
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

    const roadmap = resultHolder.current;
    if (roadmap === null) {
      setState({ phase: "error", message: "Roadmap response was malformed.", rateLimited: false });
      return;
    }
    router.push(`/roadmaps/${roadmap.id}`);
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Create a roadmap</h2>

      {papersError && (
        <p role="alert" className="text-body text-mismatch">
          {papersError}
        </p>
      )}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <label className="flex items-center gap-1.5 text-ui-label text-foreground">
          <input
            type="radio"
            name="roadmap-target-type"
            checked={targetType === "topic"}
            onChange={() => setTargetType("topic")}
            disabled={isStreaming}
          />
          Topic
        </label>
        <label className="flex items-center gap-1.5 text-ui-label text-foreground">
          <input
            type="radio"
            name="roadmap-target-type"
            checked={targetType === "paper"}
            onChange={() => setTargetType("paper")}
            disabled={isStreaming}
          />
          An owned paper
        </label>
      </div>

      {targetType === "topic" ? (
        <label className="flex flex-col gap-1 text-ui-label text-foreground" htmlFor="roadmap-topic">
          Topic
          <input
            id="roadmap-topic"
            type="text"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="e.g. diffusion models"
            disabled={isStreaming}
            className="rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
          />
        </label>
      ) : (
        <label className="flex flex-col gap-1 text-ui-label text-foreground" htmlFor="roadmap-paper">
          Target paper
          <select
            id="roadmap-paper"
            value={paperId}
            onChange={(event) => setPaperId(event.target.value)}
            disabled={isStreaming}
            className="rounded-md border border-input bg-background px-2 py-1.5 text-body text-foreground"
          >
            <option value="" disabled>
              Select a paper
            </option>
            {papers.map((paper) => (
              <option key={paper.id} value={paper.id}>
                {paper.title}
              </option>
            ))}
          </select>
        </label>
      )}

      <ProviderPicker disabled={isStreaming} needsEmbed />

      <div>
        <Button
          type="button"
          onClick={() => void handleCreate()}
          disabled={!isSelectionReady(selection, ROADMAP_NEEDS) || !hasValidTarget || isStreaming}
        >
          {isStreaming ? "Generating…" : "Create roadmap"}
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
            ? `You've hit the roadmap rate limit. Try again later. (${state.message})`
            : state.message}
        </p>
      )}
    </div>
  );
}
