"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ProviderPicker } from "@/components/provider-picker";
import { toPaperSource } from "@/lib/arxiv-input";
import type { AnalysisStage, StageConfig } from "@/lib/evidence-api";
import {
  getProviderSelection,
  isSelectionReady,
  toStageConfig,
  useProviderSelection,
  type ProviderSelection,
} from "@/lib/provider-selection-store";
import type { ProviderCatalogEntry } from "@/lib/provider-types";
import { FLOW_STAGES } from "./flow-state";
import { GenerateProgress } from "./generate-progress";
import { PaperSourceField } from "./paper-source-field";
import { PerStageModels, stageSlot } from "./per-stage-models";
import { useGenerateFlow, type GenerateInput } from "./use-generate-flow";

function SectionHeading({ index, title }: { index: number; title: string }) {
  return (
    <h2 className="flex items-center gap-3 font-display text-h3 font-medium tracking-tight text-ink">
      <span
        aria-hidden="true"
        className="flex size-7 items-center justify-center rounded-full bg-ink font-sans text-ui-label text-primary-foreground"
      >
        {index}
      </span>
      {title}
    </h2>
  );
}

/** A stage uses its own picker only when that picker is fully filled in;
 * otherwise the main model (the UI says so next to each picker). */
function resolveStages(main: ProviderSelection, perStage: boolean): Pick<GenerateInput, "stages" | "providers"> {
  const stages = {} as Record<AnalysisStage, StageConfig>;
  const providers = new Map<string, ProviderCatalogEntry>();
  for (const info of FLOW_STAGES) {
    const override = perStage ? getProviderSelection(stageSlot(info.stage)) : null;
    const chosen = override && isSelectionReady(override) ? override : main;
    stages[info.stage] = toStageConfig(chosen);
    if (chosen.provider) providers.set(chosen.provider.id, chosen.provider);
  }
  return { stages, providers: Array.from(providers.values()) };
}

export interface ComposerProps {
  /** Status poll interval; only tests change it. */
  pollIntervalMs?: number;
}

/** Home page composer: pick a paper, pick a model, Generate. */
export function Composer({ pollIntervalMs }: ComposerProps) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [perStage, setPerStage] = useState(false);
  const main = useProviderSelection();
  const flow = useGenerateFlow({ pollIntervalMs, onDone: (paperId) => router.push(`/papers/${paperId}`) });

  const source = toPaperSource(file, text);
  const busy = flow.state.phase !== "idle";
  const canGenerate = source !== null && isSelectionReady(main) && !busy;

  function handleGenerate(): void {
    if (!source || !isSelectionReady(main)) return;
    flow.start({ source, ...resolveStages(main, perStage) });
  }

  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="composer-paper" className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-6">
        <div id="composer-paper">
          <SectionHeading index={1} title="Paper" />
        </div>
        <PaperSourceField file={file} text={text} onFileChange={setFile} onTextChange={setText} disabled={busy} />
      </section>

      <section aria-labelledby="composer-model" className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-6">
        <div id="composer-model">
          <SectionHeading index={2} title="Model" />
        </div>
        <ProviderPicker disabled={busy} />

        <label className="flex items-center gap-2 text-ui-label text-ink">
          <input type="checkbox" checked={perStage} onChange={(event) => setPerStage(event.target.checked)} disabled={busy} />
          Use a different model per stage
        </label>
        {perStage && <PerStageModels disabled={busy} />}
      </section>

      <div className="flex flex-wrap items-center gap-4">
        <Button type="button" size="lg" onClick={handleGenerate} disabled={!canGenerate} className="h-11 px-6 text-body">
          Generate
        </Button>
        {!canGenerate && !busy && (
          <p className="text-caption text-muted-foreground">
            Add a paper and a model credential to continue. Keys stay in this tab and are never saved.
          </p>
        )}
      </div>

      {busy && (
        <GenerateProgress state={flow.state} onCancel={flow.cancel} onRetry={flow.retry} onDismiss={flow.dismiss} />
      )}
    </div>
  );
}
