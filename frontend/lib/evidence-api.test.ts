import { afterEach, describe, expect, it, vi } from "vitest";
import {
  extractAnalysisEvents,
  getLearning,
  getReport,
  getStory,
  getTechnicalAppendix,
  splitSseFrames,
  streamAnalysis,
} from "./evidence-api";

function sseFrame(event: string, data: object): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

describe("splitSseFrames", () => {
  it("splits multiple complete frames and keeps an incomplete tail as remainder", () => {
    const complete = sseFrame("progress", { type: "progress" }) + sseFrame("done", { type: "done" });
    const incompleteTail = "event: progress\ndata: {\"type\"";
    const { frames, remainder } = splitSseFrames(complete + incompleteTail);

    expect(frames).toHaveLength(2);
    expect(remainder).toBe(incompleteTail);
  });

  it("returns everything as remainder when no complete frame has arrived yet", () => {
    const { frames, remainder } = splitSseFrames("event: progress\ndata: {\"type\"");
    expect(frames).toHaveLength(0);
    expect(remainder).toBe("event: progress\ndata: {\"type\"");
  });
});

describe("extractAnalysisEvents", () => {
  it("parses a stream of progress/checkpoint/done events fed as one buffer", () => {
    const buffer =
      sseFrame("progress", { type: "progress", stage: "extraction", message: "Extracting claims", data: null }) +
      sseFrame("checkpoint", { type: "checkpoint", stage: "extraction", message: null, data: { claims: 3 } }) +
      sseFrame("done", { type: "done", stage: "verification", message: null, data: { paper_id: "abc" } });

    const { events, remainder } = extractAnalysisEvents(buffer);

    expect(remainder).toBe("");
    expect(events).toHaveLength(3);
    expect(events[0]).toMatchObject({ type: "progress", stage: "extraction", message: "Extracting claims" });
    expect(events[1]).toMatchObject({ type: "checkpoint", data: { claims: 3 } });
    expect(events[2]).toMatchObject({ type: "done", data: { paper_id: "abc" } });
  });

  it("dispatches an error event so a real backend failure surfaces", () => {
    const buffer = sseFrame("error", {
      type: "error",
      stage: "provider_setup",
      message: "Invalid API key",
      data: null,
    });

    const { events } = extractAnalysisEvents(buffer);
    expect(events).toEqual([{ type: "error", stage: "provider_setup", message: "Invalid API key", data: null }]);
  });

  it("carries an incomplete final frame over as remainder instead of parsing it", () => {
    const buffer = sseFrame("progress", { type: "progress" }) + "event: done\ndata: {\"type\": \"do";
    const { events, remainder } = extractAnalysisEvents(buffer);

    expect(events).toHaveLength(1);
    expect(remainder).toBe('event: done\ndata: {"type": "do');
  });

  it("drops a malformed data line instead of throwing", () => {
    const buffer = "event: progress\ndata: not-json\n\n" + sseFrame("done", { type: "done" });
    const { events } = extractAnalysisEvents(buffer);
    expect(events).toEqual([{ type: "done", stage: undefined, message: undefined, data: undefined }]);
  });

  it("ignores a frame whose data has no recognizable type field", () => {
    const buffer = "data: {\"foo\": \"bar\"}\n\n";
    const { events } = extractAnalysisEvents(buffer);
    expect(events).toHaveLength(0);
  });

  it("parses progress events tagged with the newer technical/report stages", () => {
    const buffer =
      sseFrame("progress", { type: "progress", stage: "technical", message: "Generating technical appendix" }) +
      sseFrame("progress", { type: "progress", stage: "report", message: "Generating deep report" });
    const { events } = extractAnalysisEvents(buffer);
    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ stage: "technical" });
    expect(events[1]).toMatchObject({ stage: "report" });
  });
});

describe("streamAnalysis", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs the multi-stage {stages: {...}} request body, not the old flat shape", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(sseFrame("done", { type: "done", stage: "evidence", message: null, data: null }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await streamAnalysis(
      "paper-1",
      { stages: { evidence: { provider_id: "google", api_key: "test-key" } } },
      () => {},
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      stages: { evidence: { provider_id: "google", api_key: "test-key" } },
    });
  });
});

describe("getReport / getTechnicalAppendix", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("GETs the report and technical-appendix routes and returns the section list", async () => {
    const sections = [{ id: "s1", title: "Results", content: "...", order: 0, claim_ids: ["c1"], created_at: "" }];
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(sections), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getReport("paper-1")).resolves.toEqual(sections);
    expect(fetchMock.mock.calls[0][0]).toContain("/papers/paper-1/report");

    await expect(getTechnicalAppendix("paper-1")).resolves.toEqual(sections);
    expect(fetchMock.mock.calls[1][0]).toContain("/papers/paper-1/technical-appendix");
  });
});

describe("getStory / getLearning", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("GETs the story route and returns the section list", async () => {
    const sections = [{ id: "s1", title: "Origins", content: "...", order: 0, claim_ids: ["c1"], created_at: "" }];
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(sections), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getStory("paper-1")).resolves.toEqual(sections);
    expect(fetchMock.mock.calls[0][0]).toContain("/papers/paper-1/story");
  });

  it("GETs the learning route and returns the bundled response", async () => {
    const learning = {
      paper_id: "paper-1",
      primer: [],
      application_guide: [],
      quiz: [
        {
          id: "q1",
          order: 0,
          question: "What metric was reported?",
          options: ["A", "B"],
          correct_answer: "A",
          explanation: "Because the paper says so.",
          claim_ids: ["c1"],
          created_at: "",
        },
      ],
      derivations: [
        {
          id: "d1",
          order: 0,
          title: "Loss derivation",
          steps: [{ explanation: "Start here", formula: "L = x^2", claim_ids: ["c1"] }],
          created_at: "",
        },
      ],
      interactives: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(learning), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getLearning("paper-1")).resolves.toEqual(learning);
    expect(fetchMock.mock.calls[0][0]).toContain("/papers/paper-1/learning");
  });
});

describe("streamAnalysis cancellation and local mode", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("forwards the AbortSignal to fetch and sends no Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await streamAnalysis("paper-1", { stages: {} }, () => {}, controller.signal);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBe(controller.signal);
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
  });

  it("rejects when the signal is already aborted", async () => {
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) =>
      init.signal?.aborted ? Promise.reject(init.signal.reason) : Promise.resolve(new Response("", { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    controller.abort();

    await expect(streamAnalysis("paper-1", { stages: {} }, () => {}, controller.signal)).rejects.toBeDefined();
  });
});
