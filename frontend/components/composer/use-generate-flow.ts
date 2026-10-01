"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { PaperSource } from "@/lib/arxiv-input";
import { ApiRequestError } from "@/lib/api-types";
import { streamAnalysis, type AnalysisStage, type StageConfig } from "@/lib/evidence-api";
import type { PaperResponse } from "@/lib/paper-types";
import { getPaper, resolvePaperFromArxiv, uploadPaper } from "@/lib/papers-api";
import type { ProviderCatalogEntry } from "@/lib/provider-types";
import { markExternalDataSent, markProviderUsed } from "@/lib/session-mode-store";
import { IDLE_FLOW, applyAnalysisEvent, finishAnalysis, initialStages, type FlowState } from "./flow-state";

/** Consecutive failed status polls tolerated before giving up. */
const MAX_POLL_FAILURES = 3;

export interface GenerateInput {
  source: PaperSource;
  stages: Record<AnalysisStage, StageConfig>;
  /** Distinct providers the stages use, for the local/external indicator. */
  providers: readonly ProviderCatalogEntry[];
}

export interface UseGenerateFlowOptions {
  pollIntervalMs?: number;
  onDone: (paperId: string) => void;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason);
      return;
    }
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function messageOf(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof Error) return error.message;
  return "Something went wrong.";
}

/**
 * Drives the one-page flow: create/resolve the paper, poll until parsed,
 * stream all four analysis stages, then report done. One AbortController
 * covers the whole run so Cancel works in any phase. Keys travel only inside
 * the in-memory `GenerateInput`.
 */
export function useGenerateFlow({ pollIntervalMs = 2000, onDone }: UseGenerateFlowOptions) {
  const [state, setState] = useState<FlowState>(IDLE_FLOW);
  const controllerRef = useRef<AbortController | null>(null);
  const lastInputRef = useRef<GenerateInput | null>(null);
  // Only set once a paper has parsed, so a retry after an analysis failure
  // reuses it while a retry after an upload/parse failure starts over.
  const parsedPaperIdRef = useRef<string | null>(null);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const run = useCallback(
    async (input: GenerateInput): Promise<void> => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      const { signal } = controller;
      const startedAt = Date.now();
      let current: FlowState = {
        ...IDLE_FLOW,
        phase: "preparing",
        stages: initialStages(),
        startedAt,
        lastActivityAt: startedAt,
        message: input.source.kind === "file" ? "Uploading PDF" : "Fetching paper from arXiv",
      };
      const update = (next: FlowState | Partial<FlowState>): void => {
        current = { ...current, ...next };
        setState(current);
      };
      setState(current);

      try {
        let paperId = parsedPaperIdRef.current;
        if (!paperId) {
          let paper: PaperResponse;
          if (input.source.kind === "file") {
            paper = await uploadPaper(input.source.file);
          } else {
            // The id/title is sent to arxiv.org by the backend, even with a local model.
            markExternalDataSent();
            paper = await resolvePaperFromArxiv(
              input.source.kind === "arxiv" ? { arxivId: input.source.arxivId } : { arxivTitle: input.source.title },
            );
          }
          signal.throwIfAborted();

          let failures = 0;
          while (paper.parse_status === "pending" || paper.parse_status === "parsing") {
            update({ phase: "parsing", paperId: paper.id, parseStatus: paper.parse_status, lastActivityAt: Date.now() });
            await sleep(pollIntervalMs, signal);
            try {
              paper = await getPaper(paper.id);
              failures = 0;
            } catch (error: unknown) {
              signal.throwIfAborted();
              failures += 1;
              if (failures >= MAX_POLL_FAILURES) throw error;
            }
          }
          if (paper.parse_status === "failed") {
            throw new Error(paper.parse_error ?? "The paper could not be parsed.");
          }
          parsedPaperIdRef.current = paper.id;
          paperId = paper.id;
        }

        update({
          phase: "analyzing",
          paperId,
          parseStatus: "parsed",
          message: "Starting analysis",
          lastActivityAt: Date.now(),
        });
        for (const provider of input.providers) markProviderUsed(provider);
        await streamAnalysis(
          paperId,
          { stages: input.stages },
          (event) => update(applyAnalysisEvent(current, event, Date.now())),
          signal,
        );
        const finished = finishAnalysis(current);
        update(finished);
        if (finished.phase === "done") onDoneRef.current(paperId);
      } catch (error: unknown) {
        if (signal.aborted) {
          setState(IDLE_FLOW);
          return;
        }
        update({ phase: "error", error: messageOf(error) });
      }
    },
    [pollIntervalMs],
  );

  const start = useCallback(
    (input: GenerateInput): void => {
      lastInputRef.current = input;
      parsedPaperIdRef.current = null;
      void run(input);
    },
    [run],
  );

  const retry = useCallback((): void => {
    if (lastInputRef.current) void run(lastInputRef.current);
  }, [run]);

  const cancel = useCallback((): void => {
    controllerRef.current?.abort();
    setState(IDLE_FLOW);
  }, []);

  const dismiss = useCallback((): void => setState(IDLE_FLOW), []);

  return { state, start, retry, cancel, dismiss };
}
