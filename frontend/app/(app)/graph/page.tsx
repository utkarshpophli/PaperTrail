"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ProviderPicker } from "@/components/provider-picker";
import { NeuralMap } from "@/components/neural-map";
import { ApiRequestError } from "@/lib/api-types";
import { getLibraryGraph, type LibraryGraph } from "@/lib/graph-api";
import { isSelectionReady, toStageConfig, useProviderSelection } from "@/lib/provider-selection-store";
import { markProviderUsed } from "@/lib/session-mode-store";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Could not load the graph.";
}

const GRAPH_NEEDS = { chat: false, embed: true };

type GraphState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "error"; message: string; rateLimited: boolean }
  | { phase: "done"; graph: LibraryGraph };

// Provider/credential/model come from the shared in-memory selection
// (lib/provider-selection-store.ts) — the credential is never persisted.
export default function GraphPage() {
  const router = useRouter();
  const [state, setState] = useState<GraphState>({ phase: "idle" });

  const selection = useProviderSelection();
  const selectedProvider = selection.provider;
  const isLoading = state.phase === "loading";

  async function handleLoadGraph(): Promise<void> {
    if (!selectedProvider) return;
    setState({ phase: "loading" });
    markProviderUsed(selectedProvider);
    try {
      const graph = await getLibraryGraph(toStageConfig(selection, GRAPH_NEEDS));
      setState({ phase: "done", graph });
    } catch (error: unknown) {
      const rateLimited = error instanceof ApiRequestError && error.status === 429;
      setState({ phase: "error", message: errorMessage(error), rateLimited });
    }
  }

  function handleNodeClick(nodeId: string): void {
    // Every node here is an owned, ingested Paper (unlike Discover's
    // un-ingested arXiv candidates) — an in-app reader link is correct here.
    router.push(`/papers/${nodeId}`);
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-h1 font-display font-semibold text-foreground">Literature Graph</h1>
        <p className="text-body text-muted-foreground">
          Connections across your library: semantic similarity, plus citation links and AI-classified
          relations for papers whose citations you have refreshed on their paper page. Only papers with a
          completed analysis appear here. Run analysis on a paper to add it to the graph.
        </p>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
        <ProviderPicker disabled={isLoading} needsChat={false} needsEmbed />

        <div>
          <Button
            type="button"
            onClick={() => void handleLoadGraph()}
            disabled={!isSelectionReady(selection, GRAPH_NEEDS) || isLoading}
          >
            {isLoading ? "Loading…" : "View graph"}
          </Button>
        </div>

        {state.phase === "error" && (
          <p role="alert" className="rounded-md bg-mismatch-bg px-3 py-2 text-body text-mismatch">
            {state.rateLimited
              ? `You've hit the graph rate limit. Try again later. (${state.message})`
              : state.message}
          </p>
        )}
      </div>

      {state.phase === "done" && (
        <div className="flex flex-col gap-2">
          {state.graph.nodes.length > 0 && state.graph.edges.length === 0 && (
            <p className="text-body text-muted-foreground">
              No connections yet. Analyze more papers, or refresh citations on a paper&apos;s page, to see how
              they relate.
            </p>
          )}
          <NeuralMap nodes={state.graph.nodes} edges={state.graph.edges} onNodeClick={handleNodeClick} />
        </div>
      )}
    </div>
  );
}
