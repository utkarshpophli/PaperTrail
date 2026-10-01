"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ProviderPicker } from "@/components/provider-picker";
import { ApiRequestError } from "@/lib/api-types";
import { isSelectionReady, toStageConfig, useProviderSelection } from "@/lib/provider-selection-store";
import { getRepositories } from "@/lib/coderesearch-api";
import { markExternalDataSent, markProviderUsed } from "@/lib/session-mode-store";
import {
  generateImplementationPlan,
  getImplementationPlan,
  type ClaimResponse,
} from "@/lib/evidence-api";
import { GeneratedSectionsPanel } from "./generated-sections-panel";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Implementation plan generation failed.";
}

interface ImplementationPlanPanelProps {
  paperId: string;
  claims: ClaimResponse[];
}

// Provider/credential/model come from the shared in-memory selection
// (lib/provider-selection-store.ts) -- the credential is never persisted.
export function ImplementationPlanPanel({ paperId, claims }: ImplementationPlanPanelProps) {
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [rateLimited, setRateLimited] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const selection = useProviderSelection();
  const selectedProvider = selection.provider;

  async function handleGenerate(): Promise<void> {
    if (!selectedProvider) return;
    setGenerating(true);
    setGenerateError(null);
    setRateLimited(false);
    const stageConfig = toStageConfig(selection);
    markProviderUsed(selectedProvider);
    // The backend fetches the linked repo's README from GitHub regardless of
    // the AI provider, so a linked repo means data leaves this machine. If the
    // lookup itself fails we can't rule it out, so assume it does.
    try {
      if ((await getRepositories(paperId)).length > 0) markExternalDataSent();
    } catch {
      markExternalDataSent();
    }
    try {
      await generateImplementationPlan(paperId, stageConfig);
      setRefreshKey((key) => key + 1);
    } catch (error: unknown) {
      setRateLimited(error instanceof ApiRequestError && error.status === 429);
      setGenerateError(errorMessage(error));
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
        <h2 className="text-h4 font-display font-semibold text-foreground">Implementation Plan</h2>
        <p className="text-caption text-muted-foreground">
          Read-only guidance for a human to act on manually. Generating this never runs, applies, or modifies any
          code.
        </p>

        <ProviderPicker disabled={generating} />

        <div>
          <Button type="button" onClick={() => void handleGenerate()} disabled={!isSelectionReady(selection) || generating}>
            {generating ? "Generating…" : "Generate plan"}
          </Button>
        </div>

        {generateError && (
          <p role="alert" className="rounded-md bg-mismatch-bg px-3 py-2 text-body text-mismatch">
            {rateLimited
              ? `You've hit the implementation plan rate limit (10 per hour). Try again later. (${generateError})`
              : generateError}
          </p>
        )}
      </div>

      <GeneratedSectionsPanel
        title="Implementation Plan"
        paperId={paperId}
        claims={claims}
        fetchSections={getImplementationPlan}
        notFoundCode="implementation_plan_not_found"
        refreshKey={refreshKey}
        headingLevel="h3"
      />
    </div>
  );
}
