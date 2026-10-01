"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProviderPicker } from "@/components/provider-picker";
import { NeuralMap } from "@/components/neural-map";
import { ApiRequestError } from "@/lib/api-types";
import { isSelectionReady, toStageConfig, useProviderSelection } from "@/lib/provider-selection-store";
import { markExternalDataSent, markProviderUsed } from "@/lib/session-mode-store";
import {
  streamLandscape,
  getLandscapeGraph,
  parseTopicLandscape,
  type NeuralMapGraph,
  type TopicLandscape,
} from "@/lib/discovery-api";
import type { AnalysisEvent } from "@/lib/evidence-api";
import { LandscapePaperCard } from "./landscape-paper-card";
import { LandscapePromote } from "./landscape-promote";
import { ProfileForm } from "./profile-form";
import { RecommendationsList } from "./recommendations-list";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Discovery request failed.";
}

const LANDSCAPE_NEEDS = { chat: true, embed: true };

function describeEvent(event: AnalysisEvent): string {
  if (event.type === "progress") return event.message ?? event.stage ?? "Working…";
  return event.message ?? event.type;
}

type DiscoverState =
  | { phase: "idle" }
  | { phase: "streaming"; log: string[] }
  | { phase: "error"; message: string; rateLimited: boolean }
  | { phase: "done"; landscape: TopicLandscape };

// Provider/credential/model come from the shared in-memory selection
// (lib/provider-selection-store.ts) — the credential is never persisted.
export default function DiscoverPage() {
  const [topic, setTopic] = useState("");
  const [state, setState] = useState<DiscoverState>({ phase: "idle" });
  const [graph, setGraph] = useState<NeuralMapGraph | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);

  const selection = useProviderSelection();

  useEffect(() => {
    if (state.phase !== "done") return;
    let cancelled = false;
    getLandscapeGraph(state.landscape.id)
      .then((loaded) => {
        if (!cancelled) setGraph(loaded);
      })
      .catch((error: unknown) => {
        if (!cancelled) setGraphError(errorMessage(error));
      });
    return () => {
      cancelled = true;
    };
  }, [state]);

  const selectedProvider = selection.provider;
  const isStreaming = state.phase === "streaming";

  async function handleDiscover(): Promise<void> {
    if (!selectedProvider || !topic.trim()) return;
    setState({ phase: "streaming", log: [] });
    setGraph(null);
    setGraphError(null);
    const resultHolder: { current: TopicLandscape | null } = { current: null };

    markProviderUsed(selectedProvider);
    // Topic/interest text also goes to arXiv search, whatever the AI provider.
    markExternalDataSent();
    try {
      await streamLandscape(
        {
          topic: topic.trim(),
          ...toStageConfig(selection, LANDSCAPE_NEEDS),
        },
        (event) => {
          if (event.type === "error") {
            setState({ phase: "error", message: event.message ?? "Discovery request failed.", rateLimited: false });
            return;
          }
          if (event.type === "done") {
            resultHolder.current = parseTopicLandscape(event.data);
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

    const landscape = resultHolder.current;
    if (landscape === null) {
      setState({ phase: "error", message: "Discovery response was malformed.", rateLimited: false });
      return;
    }
    setState({ phase: "done", landscape });
  }

  function handleNodeClick(nodeId: string): void {
    if (state.phase !== "done") return;
    const paper = state.landscape.papers.find((p) => p.arxiv_id === nodeId);
    if (paper) window.open(paper.pdf_url, "_blank", "noopener,noreferrer");
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-h1 font-display font-semibold text-foreground">Discover</h1>
        <p className="text-body text-muted-foreground">
          Enter a research topic to map the landscape of related papers.
        </p>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
        <label className="flex flex-col gap-1 text-ui-label text-foreground" htmlFor="discover-topic">
          Topic
          <input
            id="discover-topic"
            type="text"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="e.g. retrieval-augmented generation for code"
            disabled={isStreaming}
            className="rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
          />
        </label>

        <ProviderPicker disabled={isStreaming} needsEmbed />

        <div>
          <Button
            type="button"
            onClick={() => void handleDiscover()}
            disabled={!isSelectionReady(selection, LANDSCAPE_NEEDS) || !topic.trim() || isStreaming}
          >
            {isStreaming ? "Mapping…" : "Discover"}
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
              ? `You've hit the discovery rate limit. Try again later. (${state.message})`
              : state.message}
          </p>
        )}
      </div>

      {state.phase === "done" && (
        <>
          <LandscapePromote landscapeId={state.landscape.id} />

          <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
            <h2 className="text-h4 font-display font-semibold text-foreground">Overview</h2>
            <p className="whitespace-pre-wrap text-body text-foreground">{state.landscape.overview}</p>
          </div>

          <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
            <h2 className="text-h4 font-display font-semibold text-foreground">Method clusters</h2>
            <ul className="flex flex-col gap-2">
              {state.landscape.clusters.map((cluster) => (
                <li key={cluster.id} className="rounded-md border border-border bg-background p-3">
                  <p className="text-ui-label font-medium text-foreground">{cluster.label}</p>
                  <p className="text-body text-muted-foreground">{cluster.description}</p>
                  <p className="text-caption text-muted-foreground">{cluster.paper_ids.length} papers</p>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-col gap-2">
            <h2 className="text-h4 font-display font-semibold text-foreground">Neural map</h2>
            {graphError && (
              <p role="alert" className="text-body text-mismatch">
                {graphError}
              </p>
            )}
            {!graph && !graphError && (
              <div className="flex min-h-[320px] items-center justify-center rounded-lg border border-border bg-card p-4 text-body text-muted-foreground">
                Loading map…
              </div>
            )}
            {graph && <NeuralMap nodes={graph.nodes} edges={graph.edges} onNodeClick={handleNodeClick} />}
          </div>

          <div className="flex flex-col gap-2">
            <h2 className="text-h4 font-display font-semibold text-foreground">Papers</h2>
            <ul className="flex flex-col gap-3">
              {state.landscape.papers.map((paper) => (
                <LandscapePaperCard key={paper.arxiv_id} paper={paper} />
              ))}
            </ul>
          </div>
        </>
      )}

      <ProfileForm />
      <RecommendationsList />
    </div>
  );
}
