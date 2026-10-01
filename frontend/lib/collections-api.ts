/**
 * Mirrors backend/app/collections/schemas.py and app/collections/router.py
 * exactly — read from the FastAPI source, not just docs/API_SPEC.md.
 */

import { apiFetch } from "./api-client";

/** Mirrors app.collections.schemas.CollectionResponse. `paper_ids` are
 * owned-Paper uuids (never bare arxiv-id strings — see
 * app.collections.router.add_paper_to_collection's ownership check). */
export interface Collection {
  id: string;
  name: string;
  paper_ids: string[];
  created_at: string;
  updated_at: string;
}

export function createCollection(name: string): Promise<Collection> {
  return apiFetch<Collection>("/collections", { method: "POST", body: { name } });
}

export function listCollections(): Promise<Collection[]> {
  return apiFetch<Collection[]>("/collections");
}

export function getCollection(collectionId: string): Promise<Collection> {
  return apiFetch<Collection>(`/collections/${collectionId}`);
}

export function addPaperToCollection(collectionId: string, paperId: string): Promise<Collection> {
  return apiFetch<Collection>(`/collections/${collectionId}/papers/${paperId}`, { method: "POST" });
}

export function removePaperFromCollection(collectionId: string, paperId: string): Promise<Collection> {
  return apiFetch<Collection>(`/collections/${collectionId}/papers/${paperId}`, { method: "DELETE" });
}
