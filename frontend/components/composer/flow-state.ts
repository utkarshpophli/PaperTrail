import type { AnalysisEvent, AnalysisStage } from "@/lib/evidence-api";
import type { ParseStatus } from "@/lib/paper-types";

export interface FlowStageInfo {
  stage: AnalysisStage;
  label: string;
  hint: string;
}

/** Backend run order (see run_analysis): evidence first, then the rest. */
export const FLOW_STAGES: readonly FlowStageInfo[] = [
  { stage: "evidence", label: "Evidence", hint: "Claims, metrics and glossary, each tied to a quoted page" },
  { stage: "technical", label: "Technical", hint: "Method details and technical appendix" },
  { stage: "report", label: "Report", hint: "Deep report linked to the claims" },
  { stage: "visual", label: "Story", hint: "Story, visuals and learning layer" },
];

export type StageStatus = "waiting" | "running" | "done" | "failed";

export type FlowPhase = "idle" | "preparing" | "parsing" | "analyzing" | "done" | "error";

export interface FlowState {
  phase: FlowPhase;
  /** Set once the paper exists on the backend. */
  paperId: string | null;
  parseStatus: ParseStatus | null;
  stages: Record<AnalysisStage, StageStatus>;
  message: string | null;
  startedAt: number | null;
  /** Timestamp of the last SSE event (or phase change); drives "last activity". */
  lastActivityAt: number | null;
  error: string | null;
  /** Non-blocking issues (e.g. figure linking failed) -- the run still
   * completed, but the user should know a piece of it didn't. */
  warnings: string[];
}

export function initialStages(): Record<AnalysisStage, StageStatus> {
  return { evidence: "waiting", technical: "waiting", report: "waiting", visual: "waiting" };
}

export const IDLE_FLOW: FlowState = {
  phase: "idle",
  paperId: null,
  parseStatus: null,
  stages: initialStages(),
  message: null,
  startedAt: null,
  lastActivityAt: null,
  error: null,
  warnings: [],
};

function isFlowStage(stage: string | null): stage is AnalysisStage {
  return FLOW_STAGES.some((info) => info.stage === stage);
}

export function describeEvent(event: AnalysisEvent): string | null {
  if (event.type === "checkpoint") {
    const counts = event.data
      ? Object.entries(event.data)
          .map(([key, value]) => `${String(value)} ${key}`)
          .join(", ")
      : "";
    return counts ? `${event.stage ?? "checkpoint"}: ${counts}` : null;
  }
  return event.message ?? event.stage;
}

/** Folds one SSE event into the flow. Each stage emits its own `done`, so
 * a stage is finished by its own event, not by any global one. */
export function applyAnalysisEvent(state: FlowState, event: AnalysisEvent, now: number): FlowState {
  const next: FlowState = { ...state, lastActivityAt: now, message: describeEvent(event) ?? state.message };
  const stage = isFlowStage(event.stage) ? event.stage : null;

  if (event.type === "error") {
    const text = event.message ?? "Analysis failed.";
    const label = stage ? FLOW_STAGES.find((info) => info.stage === stage)?.label : null;
    const line = label ? `${label}: ${text}` : text;
    return {
      ...next,
      stages: stage ? { ...state.stages, [stage]: "failed" } : state.stages,
      error: state.error ? `${state.error}\n${line}` : line,
    };
  }
  if (event.type === "warning") {
    const text = event.message ?? "A non-blocking issue occurred.";
    const label = stage ? FLOW_STAGES.find((info) => info.stage === stage)?.label : null;
    return { ...next, warnings: [...state.warnings, label ? `${label}: ${text}` : text] };
  }
  if (!stage) return next;
  if (event.type === "done") return { ...next, stages: { ...state.stages, [stage]: "done" } };
  if (state.stages[stage] === "waiting") return { ...next, stages: { ...state.stages, [stage]: "running" } };
  return next;
}

/** Decides the terminal state once the SSE stream has closed. */
export function finishAnalysis(state: FlowState): FlowState {
  if (state.error) return { ...state, phase: "error" };
  const unfinished = FLOW_STAGES.filter((info) => state.stages[info.stage] !== "done");
  if (unfinished.length > 0) {
    const names = unfinished.map((info) => info.label).join(", ");
    return {
      ...state,
      phase: "error",
      error: `The analysis stream ended before every stage finished (not done: ${names}).`,
    };
  }
  return { ...state, phase: "done" };
}
