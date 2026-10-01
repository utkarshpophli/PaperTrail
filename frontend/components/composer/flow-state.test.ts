import { describe, expect, it } from "vitest";
import type { AnalysisEvent } from "@/lib/evidence-api";
import { IDLE_FLOW, applyAnalysisEvent, finishAnalysis, type FlowState } from "./flow-state";

function ev(
  type: AnalysisEvent["type"],
  stage: string | null,
  message: string | null = null,
  data: AnalysisEvent["data"] = null,
): AnalysisEvent {
  return { type, stage, message, data };
}

const RUNNING: FlowState = { ...IDLE_FLOW, phase: "analyzing" };

describe("applyAnalysisEvent", () => {
  it("moves a waiting stage to running on progress, and records the message and activity time", () => {
    const next = applyAnalysisEvent(RUNNING, ev("progress", "evidence", "Extracting claims"), 1234);
    expect(next.stages.evidence).toBe("running");
    expect(next.message).toBe("Extracting claims");
    expect(next.lastActivityAt).toBe(1234);
  });

  it("finishes a stage on its own done event, leaving the others alone", () => {
    const next = applyAnalysisEvent(RUNNING, ev("done", "evidence"), 1);
    expect(next.stages).toMatchObject({ evidence: "done", technical: "waiting" });
  });

  it("does not regress a done stage back to running", () => {
    const done = applyAnalysisEvent(RUNNING, ev("done", "evidence"), 1);
    expect(applyAnalysisEvent(done, ev("checkpoint", "evidence", null, { claims: 3 }), 2).stages.evidence).toBe("done");
  });

  it("describes checkpoints by their counts", () => {
    const next = applyAnalysisEvent(RUNNING, ev("checkpoint", "evidence", null, { claims: 12, metrics: 4 }), 1);
    expect(next.message).toBe("evidence: 12 claims, 4 metrics");
  });

  it("fails the stage on error and keeps the exact text; later errors append", () => {
    const first = applyAnalysisEvent(RUNNING, ev("error", "technical", "Provider timed out"), 1);
    expect(first.stages.technical).toBe("failed");
    expect(first.error).toBe("Technical: Provider timed out");
    const second = applyAnalysisEvent(first, ev("error", "report", "Bad JSON"), 2);
    expect(second.error).toBe("Technical: Provider timed out\nReport: Bad JSON");
  });

  it("keeps a stage-less error's text as is", () => {
    expect(applyAnalysisEvent(RUNNING, ev("error", null, "Boom"), 1).error).toBe("Boom");
  });

  it("collects a warning without failing its stage or setting error", () => {
    const next = applyAnalysisEvent(RUNNING, ev("warning", "visual", "Figure linking failed: timed out"), 1);
    expect(next.warnings).toEqual(["Story: Figure linking failed: timed out"]);
    expect(next.stages.visual).toBe("waiting");
    expect(next.error).toBeNull();
  });
});

describe("finishAnalysis", () => {
  const allDone = ["evidence", "technical", "report", "visual"].reduce(
    (state, stage) => applyAnalysisEvent(state, ev("done", stage), 1),
    RUNNING,
  );

  it("is done when every stage is done", () => {
    expect(finishAnalysis(allDone).phase).toBe("done");
  });

  it("is still done when a warning was reported alongside successful stages", () => {
    const withWarning = applyAnalysisEvent(allDone, ev("warning", "visual", "Figure linking failed"), 2);
    expect(finishAnalysis(withWarning).phase).toBe("done");
    expect(withWarning.warnings).toEqual(["Story: Figure linking failed"]);
  });

  it("is an error when any stage reported one, even if others finished", () => {
    const failed = applyAnalysisEvent(allDone, ev("error", "visual", "x"), 2);
    expect(finishAnalysis(failed).phase).toBe("error");
  });

  it("is an error naming the unfinished stages when the stream ends early", () => {
    const partial = applyAnalysisEvent(RUNNING, ev("done", "evidence"), 1);
    const result = finishAnalysis(partial);
    expect(result.phase).toBe("error");
    expect(result.error).toContain("Technical, Report, Story");
  });
});
