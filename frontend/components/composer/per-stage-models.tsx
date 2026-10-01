"use client";

import { ProviderPicker } from "@/components/provider-picker";
import { isSelectionReady, useProviderSelection } from "@/lib/provider-selection-store";
import type { AnalysisStage } from "@/lib/evidence-api";
import { FLOW_STAGES } from "./flow-state";

/** Selection slot backing one stage's optional override picker. */
export function stageSlot(stage: AnalysisStage): string {
  return `stage-${stage}`;
}

function StageModel({ stage, label, disabled }: { stage: AnalysisStage; label: string; disabled: boolean }) {
  const selection = useProviderSelection(stageSlot(stage));
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line bg-background p-3">
      <h4 className="text-ui-label font-medium text-ink">{label} stage</h4>
      <ProviderPicker slot={stageSlot(stage)} label={`${label} stage`} disabled={disabled} />
      <p className="text-caption text-muted-foreground">
        {isSelectionReady(selection)
          ? "This stage uses the model chosen here."
          : "Enter an API key or endpoint to override; until then this stage uses the main model."}
      </p>
    </div>
  );
}

/** Optional per-stage overrides. A stage whose picker has no credential falls
 * back to the main model, and says so. */
export function PerStageModels({ disabled = false }: { disabled?: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      {FLOW_STAGES.map((info) => (
        <StageModel key={info.stage} stage={info.stage} label={info.label} disabled={disabled} />
      ))}
    </div>
  );
}
