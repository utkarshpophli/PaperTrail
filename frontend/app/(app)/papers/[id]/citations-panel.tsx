"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ProviderPicker } from "@/components/provider-picker";
import { ApiRequestError } from "@/lib/api-types";
import { refreshCitations, type CitationEdge } from "@/lib/graph-api";
import { RELATION_LABELS, describeRelationProvenance } from "@/lib/literature-relations";
import { getPapers } from "@/lib/papers-api";
import { isSelectionReady, toStageConfig, useProviderSelection } from "@/lib/provider-selection-store";
import { markExternalDataSent, markProviderUsed } from "@/lib/session-mode-store";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Citation refresh failed.";
}

/** Maps the two failure modes worth distinguishing (rate limit, OpenAlex
 * outage) to specific text; anything else shows the backend's own message. */
function refreshFailureMessage(error: unknown): string {
  if (error instanceof ApiRequestError && error.status === 429) {
    return `You've hit the citation refresh rate limit (5 per hour). Try again later. (${error.message})`;
  }
  if (error instanceof ApiRequestError && error.status === 502) {
    return `OpenAlex could not be reached, so no citations were refreshed. Try again later. (${error.message})`;
  }
  return errorMessage(error);
}

interface CitationsPanelProps {
  paperId: string;
}

// Provider/credential/model come from the shared in-memory selection
// (lib/provider-selection-store.ts) -- the credential is never persisted.
export function CitationsPanel({ paperId }: CitationsPanelProps) {
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [results, setResults] = useState<CitationEdge[] | null>(null);
  const [titlesById, setTitlesById] = useState<Map<string, string>>(new Map());

  const selection = useProviderSelection();
  const selectedProvider = selection.provider;

  async function handleRefresh(): Promise<void> {
    if (!selectedProvider) return;
    setRefreshing(true);
    setRefreshError(null);
    // Two independent egress paths: the AI provider (cloud only) and OpenAlex
    // (always -- titles/DOIs go there even with a local model).
    markProviderUsed(selectedProvider);
    markExternalDataSent();
    try {
      const edges = await refreshCitations(paperId, toStageConfig(selection));
      // Titles are enrichment: if this local lookup fails, rows fall back to a
      // visibly-labeled short id rather than hiding the refreshed citations.
      const papers = await getPapers().catch(() => []);
      setTitlesById(new Map(papers.map((paper) => [paper.id, paper.title])));
      setResults(edges);
    } catch (error: unknown) {
      setRefreshError(refreshFailureMessage(error));
    } finally {
      setRefreshing(false);
    }
  }

  function otherPaperTitle(edge: CitationEdge): string {
    const otherId = edge.from_paper_id === paperId ? edge.to_paper_id : edge.from_paper_id;
    return titlesById.get(otherId) ?? `Untitled paper (${otherId.slice(0, 8)})`;
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Citations</h2>
      <p className="text-caption text-muted-foreground">
        Finds which of your other papers this one cites (or is cited by), using OpenAlex, then asks your chosen model
        to label how they relate.
      </p>
      <p className="text-caption font-medium text-foreground">
        Sends this paper&apos;s and your other papers&apos; titles/DOIs to OpenAlex (api.openalex.org), even when
        using a local model.
      </p>

      <ProviderPicker disabled={refreshing} />

      <div>
        <Button type="button" onClick={() => void handleRefresh()} disabled={!isSelectionReady(selection) || refreshing}>
          {refreshing ? "Refreshing…" : "Refresh citations"}
        </Button>
      </div>

      {refreshError && (
        <p role="alert" className="rounded-md bg-mismatch-bg px-3 py-2 text-body text-mismatch">
          {refreshError}
        </p>
      )}

      {results !== null && results.length === 0 && (
        <p className="text-body text-muted-foreground">
          OpenAlex has no record of this paper, or none of your other papers are cited by it.
        </p>
      )}

      {results !== null && results.length > 0 && (
        <ul className="flex flex-col gap-2">
          {results.map((edge) => {
            const outgoing = edge.from_paper_id === paperId;
            const title = otherPaperTitle(edge);
            return (
              <li key={edge.id} className="flex flex-col gap-0.5 rounded-md border border-border bg-background p-3">
                <p className="text-body text-foreground">
                  <span className="font-medium">{RELATION_LABELS[edge.relation]}</span>
                  {": "}
                  <span>{outgoing ? `this paper → ${title}` : `${title} → this paper`}</span>
                </p>
                <p className="text-caption text-muted-foreground">
                  {describeRelationProvenance(edge.relation, edge.confidence)}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
