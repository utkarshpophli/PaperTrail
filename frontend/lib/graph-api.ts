/**
 * Mirrors backend/app/graph/schemas.py and app/graph/router.py exactly —
 * read from the FastAPI source, not just docs/API_SPEC.md.
 *
 * Kept decoupled from lib/discovery-api.ts's structurally-identical
 * NeuralMapNode/NeuralMapEdge/NeuralMapGraph types, mirroring
 * app.graph.schemas's own module docstring: Discovery and this Phase 7
 * sibling stay decoupled on purpose. `<NeuralMap>` accepts either by
 * structural typing.
 */

import { apiFetch } from "./api-client";
import type { LiteratureEdgeRelation } from "./literature-relations";

export type { LiteratureEdgeRelation };

/** Mirrors app.graph.schemas.GraphNode. */
export interface GraphNode {
  id: string;
  label: string;
  color: string;
  size: number | null;
}

/** Mirrors app.graph.schemas.GraphEdge. `relation` is the full 12-value
 * enum: `semantically_similar` (live, embedding-derived), `cites` (OpenAlex
 * record, weight 1.0) and the refined types (classifier guesses, weight = the
 * model's own confidence). */
export interface GraphEdge {
  source: string;
  target: string;
  relation: LiteratureEdgeRelation;
  weight: number | null;
}

/** Mirrors app.graph.schemas.LibraryGraphResponse. */
export interface LibraryGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphProviderParams {
  provider_id: string;
  /** Sent as the `X-Provider-Api-Key` header, never a query param — same
   * transport as GetRecommendationsParams (app.graph.router's module
   * docstring: a secret in the URL is trivially captured by access/proxy
   * logs). */
  api_key?: string;
  endpoint?: string;
  /** The graph is built purely from embedding similarity -- there is no
   * chat-model field on these two routes at all. */
  embed_model?: string;
}

function buildQuery(params: GraphProviderParams): string {
  const query = new URLSearchParams({ provider_id: params.provider_id, embed_model: params.embed_model ?? "" });
  if (params.endpoint) query.set("endpoint", params.endpoint);
  return query.toString();
}

function authHeaders(params: GraphProviderParams): HeadersInit | undefined {
  return params.api_key ? { "X-Provider-Api-Key": params.api_key } : undefined;
}

export function getLibraryGraph(params: GraphProviderParams): Promise<LibraryGraph> {
  return apiFetch<LibraryGraph>(`/graph?${buildQuery(params)}`, { headers: authHeaders(params) });
}

export function getPaperNeighbors(paperId: string, params: GraphProviderParams): Promise<LibraryGraph> {
  return apiFetch<LibraryGraph>(`/graph/papers/${paperId}/neighbors?${buildQuery(params)}`, {
    headers: authHeaders(params),
  });
}

/** Mirrors app.graph.schemas.CitationEdgeResponse. `from_paper_id` cites
 * `to_paper_id`; `confidence` is 1.0 for a plain OpenAlex `cites` record and
 * the classifier's own confidence for any refined relation. */
export interface CitationEdge {
  id: string;
  from_paper_id: string;
  to_paper_id: string;
  relation: LiteratureEdgeRelation;
  confidence: number;
  openalex_work_id: string;
  fetched_at: string;
}

/** Mirrors app.graph.router.CitationRefreshRequest. The key is sent in the
 * body (a state-changing POST, unlike the GET routes' header) and is never
 * persisted client-side. */
export interface CitationRefreshRequest {
  provider_id: string;
  api_key?: string;
  endpoint?: string;
  model?: string;
}

export function refreshCitations(paperId: string, request: CitationRefreshRequest): Promise<CitationEdge[]> {
  return apiFetch<CitationEdge[]>(`/graph/papers/${paperId}/citations/refresh`, { method: "POST", body: request });
}
