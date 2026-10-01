import { afterEach, describe, expect, it, vi } from "vitest";
import { getLibraryGraph, getPaperNeighbors, refreshCitations } from "./graph-api";

const GRAPH = {
  nodes: [{ id: "paper-1", label: "RAG Paper", color: "#ff0000", size: 5 }],
  edges: [{ source: "paper-1", target: "paper-2", relation: "semantically_similar" as const, weight: 0.8 }],
};

describe("graph-api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("GETs /graph with provider_id/embed_model as query params and api_key via the X-Provider-Api-Key header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(GRAPH), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      getLibraryGraph({ provider_id: "google", api_key: "k", embed_model: "text-embedding-3-small" }),
    ).resolves.toEqual(GRAPH);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/graph?");
    expect(url).toContain("provider_id=google");
    expect(url).toContain("embed_model=text-embedding-3-small");
    expect(url).not.toContain("api_key");
    expect(new Headers(init.headers).get("X-Provider-Api-Key")).toBe("k");
  });

  it("GETs /graph/papers/{id}/neighbors with the same provider/credential pattern", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(GRAPH), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getPaperNeighbors("paper-1", { provider_id: "google", api_key: "k" })).resolves.toEqual(GRAPH);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/graph/papers/paper-1/neighbors?provider_id=google");
    expect(new Headers(init.headers).get("X-Provider-Api-Key")).toBe("k");
  });

  it("omits the X-Provider-Api-Key header entirely when no api_key is given (local providers)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(GRAPH), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await getLibraryGraph({ provider_id: "ollama", endpoint: "http://localhost:11434" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("X-Provider-Api-Key")).toBeNull();
  });

  it("POSTs the provider selection to /graph/papers/{id}/citations/refresh as a JSON body and returns the edges", async () => {
    const edges = [
      {
        id: "e1",
        from_paper_id: "paper-1",
        to_paper_id: "paper-2",
        relation: "extends" as const,
        confidence: 0.72,
        openalex_work_id: "W1",
        fetched_at: "2024-01-01T00:00:00Z",
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(edges), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(refreshCitations("paper-1", { provider_id: "google", api_key: "k" })).resolves.toEqual(edges);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/graph/papers/paper-1/citations/refresh");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ provider_id: "google", api_key: "k" });
  });
});
