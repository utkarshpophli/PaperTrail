"use client";

import { useEffect, useRef, useState } from "react";
import { CircleCheck, CircleDashed, CircleX, Loader2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ParseStatusIndicator } from "@/components/parse-status-indicator";
import { cn } from "@/lib/utils";
import { FLOW_STAGES, type FlowState, type StageStatus } from "./flow-state";

export function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

const STAGE_STATUS: Record<StageStatus, { text: string; icon: typeof Loader2; className: string }> = {
  waiting: { text: "Waiting", icon: CircleDashed, className: "text-muted-foreground" },
  running: { text: "Running", icon: Loader2, className: "text-ink" },
  done: { text: "Done", icon: CircleCheck, className: "text-verified" },
  failed: { text: "Failed", icon: CircleX, className: "text-mismatch" },
};

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

export interface GenerateProgressProps {
  state: FlowState;
  onCancel: () => void;
  onRetry: () => void;
  onDismiss: () => void;
}

/** Modal progress panel for the composer's run. Status is always text plus an
 * icon, never color alone; the live message sits in an aria-live region. */
export function GenerateProgress({ state, onCancel, onRetry, onDismiss }: GenerateProgressProps) {
  const active = state.phase === "preparing" || state.phase === "parsing" || state.phase === "analyzing";
  const now = useNow(active);
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  const elapsed = state.startedAt ? (now - state.startedAt) / 1000 : 0;
  const idle = state.lastActivityAt ? Math.max(0, (now - state.lastActivityAt) / 1000) : 0;
  const failed = state.phase === "error";
  const evidenceDone = state.stages.evidence === "done";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="generate-progress-title"
        tabIndex={-1}
        className="flex max-h-full w-full max-w-xl flex-col gap-5 overflow-y-auto rounded-2xl border border-line bg-surface p-6 shadow-xl outline-none"
      >
        <div className="flex flex-col gap-1">
          <h2 id="generate-progress-title" className="font-display text-h3 font-medium tracking-tight text-ink">
            {failed ? "Generation stopped" : state.phase === "done" ? "Opening your paper" : "Reading your paper"}
          </h2>
          <p className="text-ui-label text-muted-foreground">
            Elapsed {formatDuration(elapsed)}
            {active && <> · Last activity {Math.floor(idle)}s ago</>}
          </p>
        </div>

        {(state.phase === "preparing" || state.phase === "parsing") && (
          <div className="flex items-center gap-2 text-body text-ink">
            <span>{state.phase === "preparing" ? state.message : "Parsing the PDF and extracting figures (on this machine)"}</span>
            {state.parseStatus && <ParseStatusIndicator status={state.parseStatus} />}
          </div>
        )}

        <ol className="flex flex-col gap-2">
          {FLOW_STAGES.map((info, index) => {
            const status = STAGE_STATUS[state.stages[info.stage]];
            const Icon = status.icon;
            return (
              <li
                key={info.stage}
                data-stage={info.stage}
                className="flex items-start gap-3 rounded-lg border border-line bg-background px-3 py-2"
              >
                <span
                  aria-hidden="true"
                  className="flex size-6 shrink-0 items-center justify-center rounded-full bg-secondary text-caption font-medium text-ink"
                >
                  {index + 1}
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="text-body font-medium text-ink">{info.label}</span>
                  <span className="text-caption text-muted-foreground">{info.hint}</span>
                </div>
                <span className={cn("inline-flex items-center gap-1 text-ui-label font-medium", status.className)}>
                  <Icon
                    className={cn("size-4", state.stages[info.stage] === "running" && "animate-spin motion-reduce:animate-none")}
                    aria-hidden="true"
                  />
                  {status.text}
                </span>
              </li>
            );
          })}
        </ol>

        <p aria-live="polite" className="min-h-6 text-body text-ink-soft">
          {active && state.phase === "analyzing" ? state.message : null}
        </p>

        {state.warnings.length > 0 && (
          <ul role="status" className="flex flex-col gap-1 rounded-lg bg-secondary px-3 py-2">
            {state.warnings.map((warning, index) => (
              <li key={index} className="flex items-start gap-2 text-body text-ink-soft">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <span>{warning}</span>
              </li>
            ))}
          </ul>
        )}

        {failed && state.error && (
          <p role="alert" className="whitespace-pre-wrap rounded-lg bg-mismatch-bg px-3 py-2 text-body text-mismatch">
            {state.error}
          </p>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          {active && (
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
          )}
          {failed && (
            <>
              {state.paperId && evidenceDone && (
                <Button asChild variant="outline">
                  <Link href={`/papers/${state.paperId}`}>Open paper anyway</Link>
                </Button>
              )}
              <Button type="button" variant="outline" onClick={onDismiss}>
                Close
              </Button>
              <Button type="button" onClick={onRetry}>
                Try again
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
