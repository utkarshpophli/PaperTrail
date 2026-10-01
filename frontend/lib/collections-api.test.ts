import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addPaperToCollection,
  createCollection,
  getCollection,
  listCollections,
  removePaperFromCollection,
} from "./collections-api";

const COLLECTION = {
  id: "collection-1",
  name: "Diffusion models",
  paper_ids: ["paper-1"],
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

describe("collections-api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs {name} to /collections", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(COLLECTION), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createCollection("Diffusion models")).resolves.toEqual(COLLECTION);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/collections");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ name: "Diffusion models" });
  });

  it("GETs the collection list as a plain array", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([COLLECTION]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listCollections()).resolves.toEqual([COLLECTION]);
    expect(fetchMock.mock.calls[0][0]).toContain("/collections");
  });

  it("GETs a collection by id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(COLLECTION), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getCollection("collection-1")).resolves.toEqual(COLLECTION);
    expect(fetchMock.mock.calls[0][0]).toContain("/collections/collection-1");
  });

  it("POSTs to add a paper to a collection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(COLLECTION), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(addPaperToCollection("collection-1", "paper-1")).resolves.toEqual(COLLECTION);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/collections/collection-1/papers/paper-1");
    expect(init.method).toBe("POST");
  });

  it("DELETEs to remove a paper from a collection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(COLLECTION), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(removePaperFromCollection("collection-1", "paper-1")).resolves.toEqual(COLLECTION);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/collections/collection-1/papers/paper-1");
    expect(init.method).toBe("DELETE");
  });
});
