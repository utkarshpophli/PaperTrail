import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getLandscape,
  getLandscapeGraph,
  getProfile,
  getRecommendations,
  getRoadmap,
  listRoadmaps,
  parseRoadmap,
  parseTopicLandscape,
  promoteLandscape,
  streamLandscape,
  streamRoadmap,
  updateMilestoneStatus,
  updateProfile,
} from "./discovery-api";

function sseFrame(event: string, data: object): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

const LANDSCAPE = {
  id: "landscape-1",
  topic: "retrieval-augmented generation",
  overview: "RAG combines retrieval with generation.",
  papers: [
    {
      arxiv_id: "1234.5678",
      title: "RAG Paper",
      authors: ["A. Author"],
      year: 2023,
      pdf_url: "https://arxiv.org/pdf/1234.5678",
      abstract: "We propose RAG.",
      relevance_score: 0.9,
      cluster_id: "cluster-1",
      extraction: {
        tldr: { text: "Combines retrieval and generation.", verification_status: "verified" },
        problem: { text: "LLMs hallucinate without external grounding.", verification_status: "partially-matched" },
        method: { text: "Dense retrieval + seq2seq.", verification_status: "verified" },
        results: { text: "Improves factuality on QA benchmarks.", verification_status: "needs-review" },
        why_it_matters: { text: "Grounds generation in retrieved evidence.", verification_status: "not-found" },
      },
    },
    {
      arxiv_id: "9999.0001",
      title: "Un-extracted Paper",
      authors: [],
      year: null,
      pdf_url: "https://arxiv.org/pdf/9999.0001",
      abstract: "A paper the extraction stage hasn't reached yet.",
      relevance_score: 0.5,
      cluster_id: null,
      extraction: null,
    },
  ],
  clusters: [
    { id: "cluster-1", label: "Retrieval methods", description: "Dense retrieval approaches.", paper_ids: ["1234.5678"] },
  ],
  created_at: "2024-01-01T00:00:00Z",
};

describe("parseTopicLandscape", () => {
  it("narrows a valid done-event payload, preserving a paper's null extraction", () => {
    const parsed = parseTopicLandscape(LANDSCAPE);
    expect(parsed).toEqual(LANDSCAPE);
    expect(parsed?.papers[1].extraction).toBeNull();
    expect(parsed?.papers[0].extraction?.tldr.verification_status).toBe("verified");
  });

  it("returns null for a payload missing required fields", () => {
    expect(parseTopicLandscape({ id: "x" })).toBeNull();
  });

  it("returns null when a paper entry is malformed", () => {
    const malformed = { ...LANDSCAPE, papers: [{ title: "missing arxiv_id" }] };
    expect(parseTopicLandscape(malformed)).toBeNull();
  });

  it("returns null when a present extraction field is missing its verification_status", () => {
    const malformed = {
      ...LANDSCAPE,
      papers: [{ ...LANDSCAPE.papers[0], extraction: { ...LANDSCAPE.papers[0].extraction, tldr: { text: "x" } } }],
    };
    expect(parseTopicLandscape(malformed)).toBeNull();
  });

  it("returns null for null input", () => {
    expect(parseTopicLandscape(null)).toBeNull();
  });
});

describe("streamLandscape", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs the {topic, provider_id, ...} request body to /discover/landscape", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(sseFrame("done", { type: "done", stage: null, message: null, data: LANDSCAPE }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const events: unknown[] = [];
    await streamLandscape(
      { topic: "retrieval-augmented generation", provider_id: "google", api_key: "test-key" },
      (event) => events.push(event),
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discover/landscape");
    expect(JSON.parse(init.body as string)).toEqual({
      topic: "retrieval-augmented generation",
      provider_id: "google",
      api_key: "test-key",
    });
    expect(events).toHaveLength(1);
    expect((events[0] as { data: unknown }).data).toEqual(LANDSCAPE);
  });
});

describe("landscape/profile/recommendation GETs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("GETs a landscape by id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(LANDSCAPE), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getLandscape("landscape-1")).resolves.toEqual(LANDSCAPE);
    expect(fetchMock.mock.calls[0][0]).toContain("/discover/landscape/landscape-1");
  });

  it("GETs a landscape's graph", async () => {
    const graph = {
      nodes: [{ id: "1234.5678", label: "RAG Paper", color: "#ff0000", size: 5 }],
      edges: [{ source: "1234.5678", target: "1111.2222", relation: "semantically_similar", weight: 0.8 }],
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(graph), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getLandscapeGraph("landscape-1")).resolves.toEqual(graph);
    expect(fetchMock.mock.calls[0][0]).toContain("/discover/landscape/landscape-1/graph");
  });

  it("GETs and PUTs the recommendation profile", async () => {
    const profile = { interests: ["nlp"], level: "intermediate" as const, goals: ["stay current"] };
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(profile), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getProfile()).resolves.toEqual(profile);
    expect(fetchMock.mock.calls[0][0]).toContain("/discover/profile");

    await expect(updateProfile(profile)).resolves.toEqual(profile);
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual(profile);
  });

  it("GETs recommendations as a plain array, sending api_key via the X-Provider-Api-Key header (never a query param)", async () => {
    const response: unknown[] = [];
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      getRecommendations({ provider_id: "google", api_key: "k", embed_model: "text-embedding-3-small" }),
    ).resolves.toEqual(response);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discover/recommendations?");
    expect(url).toContain("provider_id=google");
    expect(url).toContain("embed_model=text-embedding-3-small");
    expect(url).not.toContain("api_key");
    expect(new Headers(init.headers).get("X-Provider-Api-Key")).toBe("k");
  });

  it("POSTs to promote a landscape into a collection, returning added/skipped_not_ingested", async () => {
    const response = { collection_id: "collection-1", added: ["1234.5678"], skipped_not_ingested: ["9999.0001"] };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(promoteLandscape("landscape-1", { collection_name: "RAG papers" })).resolves.toEqual(response);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discover/landscape/landscape-1/promote");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ collection_name: "RAG papers" });
  });
});

const ROADMAP = {
  id: "roadmap-1",
  target_description: "diffusion models",
  target_paper_id: null,
  concepts: [
    {
      id: "concept-1",
      name: "Denoising",
      description: "Iteratively removing noise from a sample.",
      source_paper_id: null,
      source_arxiv_id: "1234.5678",
      grounding_excerpt: "we denoise the sample iteratively",
      verification_status: "verified",
    },
    {
      id: "concept-2",
      name: "Score matching",
      description: "Estimating the gradient of the log density.",
      source_paper_id: null,
      source_arxiv_id: "1234.5678",
      grounding_excerpt: "score matching estimates the gradient",
      verification_status: "verified",
    },
  ],
  edges: [{ concept_id: "concept-1", prerequisite_concept_id: "concept-2" }],
  milestones: [
    {
      id: "milestone-1",
      order: 1,
      paper_id: null,
      arxiv_id: "1234.5678",
      title: "Score-based generative modeling",
      concept_ids: ["concept-1", "concept-2"],
      status: "available",
    },
  ],
  overview: "This roadmap builds up diffusion models from first principles.",
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

describe("parseRoadmap", () => {
  it("narrows a valid done-event payload", () => {
    expect(parseRoadmap(ROADMAP)).toEqual(ROADMAP);
  });

  it("returns null for a payload missing required fields", () => {
    expect(parseRoadmap({ id: "x" })).toBeNull();
  });

  it("returns null when a concept is missing verification_status", () => {
    const malformed = { ...ROADMAP, concepts: [{ ...ROADMAP.concepts[0], verification_status: undefined }] };
    expect(parseRoadmap(malformed)).toBeNull();
  });

  it("returns null when a milestone has an invalid status", () => {
    const malformed = { ...ROADMAP, milestones: [{ ...ROADMAP.milestones[0], status: "archived" }] };
    expect(parseRoadmap(malformed)).toBeNull();
  });

  it("returns null for null input", () => {
    expect(parseRoadmap(null)).toBeNull();
  });
});

describe("streamRoadmap", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs the {target, provider_id, ...} request body to /discover/roadmap", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(sseFrame("done", { type: "done", stage: null, message: null, data: ROADMAP }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const events: unknown[] = [];
    await streamRoadmap(
      { target: { type: "topic", topic: "diffusion models" }, provider_id: "google", api_key: "test-key" },
      (event) => events.push(event),
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discover/roadmap");
    expect(JSON.parse(init.body as string)).toEqual({
      target: { type: "topic", topic: "diffusion models" },
      provider_id: "google",
      api_key: "test-key",
    });
    expect((events[0] as { data: unknown }).data).toEqual(ROADMAP);
  });
});

describe("roadmap GET/PATCH", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("GETs a roadmap by id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(ROADMAP), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getRoadmap("roadmap-1")).resolves.toEqual(ROADMAP);
    expect(fetchMock.mock.calls[0][0]).toContain("/discover/roadmap/roadmap-1");
  });

  it("GETs the roadmap list as a plain array", async () => {
    const summaries = [{ id: "roadmap-1", target_description: "diffusion models", created_at: "2024-01-01T00:00:00Z", milestone_count: 3, completed_count: 1 }];
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(summaries), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listRoadmaps()).resolves.toEqual(summaries);
    expect(fetchMock.mock.calls[0][0]).toContain("/discover/roadmaps");
  });

  it("PATCHes a milestone's status, never sending 'locked'", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(ROADMAP), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(updateMilestoneStatus("roadmap-1", "milestone-1", "completed")).resolves.toEqual(ROADMAP);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discover/roadmap/roadmap-1/milestones/milestone-1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ status: "completed" });
  });
});
