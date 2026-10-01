"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ProviderPicker } from "@/components/provider-picker";
import { ApiRequestError } from "@/lib/api-types";
import { isSelectionReady, toStageConfig, useProviderSelection } from "@/lib/provider-selection-store";
import { markExternalDataSent, markProviderUsed } from "@/lib/session-mode-store";
import { getRecommendations, type Recommendation } from "@/lib/discovery-api";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Could not load recommendations.";
}

function arxivAbsUrl(arxivId: string): string {
  return `https://arxiv.org/abs/${arxivId}`;
}

/** Profile-driven "papers for you" list, `GET /discover/recommendations`.
 * Provider/credential/model come from the shared in-memory
 * selection (lib/provider-selection-store.ts) — never persisted. */
const NEEDS = { chat: false, embed: true };

export function RecommendationsList() {
  const [recommendations, setRecommendations] = useState<Recommendation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const selection = useProviderSelection();
  const selectedProvider = selection.provider;

  async function handleFetch(): Promise<void> {
    if (!selectedProvider) return;
    setLoading(true);
    setError(null);
    markProviderUsed(selectedProvider);
    // Topic/interest text also goes to arXiv search, whatever the AI provider.
    markExternalDataSent();
    try {
      const response = await getRecommendations(toStageConfig(selection, NEEDS));
      setRecommendations(response);
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Recommended for you</h2>

      <ProviderPicker disabled={loading} needsChat={false} needsEmbed />

      <div>
        <Button
          type="button"
          onClick={() => void handleFetch()}
          disabled={!isSelectionReady(selection, NEEDS) || loading}
        >
          {loading ? "Loading…" : "Get recommendations"}
        </Button>
      </div>

      {error && (
        <p role="alert" className="text-body text-mismatch">
          {error}
        </p>
      )}

      {recommendations && recommendations.length === 0 && (
        <p className="text-body text-muted-foreground">No recommendations yet. Try setting your profile above.</p>
      )}

      {recommendations && recommendations.length > 0 && (
        <ul className="flex flex-col gap-2">
          {recommendations.map((rec) => (
            <li key={rec.arxiv_id} className="flex flex-col gap-1 rounded-md border border-border bg-background p-3">
              <div className="flex items-start justify-between gap-3">
                <p className="text-ui-label font-medium text-foreground">{rec.title}</p>
                <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-caption font-medium text-foreground">
                  {Math.round(rec.relevance_score * 100)}%
                </span>
              </div>
              <p className="text-caption text-muted-foreground">{rec.authors.join(", ") || "Unknown authors"}</p>
              <p className="text-body text-foreground">{rec.explanation}</p>
              <a
                href={arxivAbsUrl(rec.arxiv_id)}
                target="_blank"
                rel="noreferrer"
                className="text-ui-label text-primary hover:underline"
              >
                Open on arXiv
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
