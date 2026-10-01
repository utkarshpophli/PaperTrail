/**
 * Mirrors backend/app/discovery/schemas.py and app/discovery/router.py
 * exactly — read from the FastAPI source (Phase 5, landed in parallel by the
 * recommendation-engineer agent), not just the dispatch spec/docs/API_SPEC.md.
 */

import { apiFetch } from "./api-client";
import { streamSse, type AnalysisEvent, type VerificationStatus } from "./evidence-api";
import type { LiteratureEdgeRelation } from "./literature-relations";

/** Mirrors DiscoveryProviderConfig + LandscapeSearchRequest -- needs both a
 * chat model (extraction/clustering) and an embed model (relevance ranking). */
export interface DiscoverLandscapeRequest {
  topic: string;
  provider_id: string;
  api_key?: string;
  endpoint?: string;
  model?: string;
  embed_model?: string;
}

/** Mirrors app.discovery.schemas.ExtractedField — the model's synthesized
 * text plus the independent verifier's judgment on whether its supporting
 * excerpt appears in the abstract. Set only by the verifier, same discipline
 * as Claim.verification_status; never render `text` without this badge. */
export interface ExtractedField {
  text: string;
  verification_status: VerificationStatus;
}

/** Mirrors app.discovery.schemas.PaperExtractionCard. */
export interface PaperExtractionCard {
  tldr: ExtractedField;
  problem: ExtractedField;
  method: ExtractedField;
  results: ExtractedField;
  why_it_matters: ExtractedField;
}

/** Mirrors app.discovery.schemas.LandscapePaperItem. `extraction` is `null`
 * until the extraction stage has run for this paper — render an "extraction
 * unavailable" state, never a blank card. */
export interface LandscapePaper {
  arxiv_id: string;
  title: string;
  authors: string[];
  year: number | null;
  pdf_url: string;
  abstract: string;
  relevance_score: number;
  cluster_id: string | null;
  extraction: PaperExtractionCard | null;
}

/** Mirrors app.discovery.schemas.MethodClusterItem. */
export interface MethodCluster {
  id: string;
  label: string;
  description: string;
  paper_ids: string[];
}

/** Mirrors app.discovery.schemas.TopicLandscapeResponse. */
export interface TopicLandscape {
  id: string;
  topic: string;
  overview: string;
  papers: LandscapePaper[];
  clusters: MethodCluster[];
  created_at: string;
}

/** Mirrors app.discovery.schemas.GraphNode. */
export interface NeuralMapNode {
  id: string;
  label: string;
  color: string;
  size: number | null;
}

/** Mirrors app.discovery.schemas.GraphEdge. `relation` is widened to the
 * shared 12-value union because <NeuralMap> is the generic Neural Map contract
 * that Phase 7's library graph also feeds (Discover itself still only emits
 * "semantically_similar"). */
export interface NeuralMapEdge {
  source: string;
  target: string;
  relation: LiteratureEdgeRelation;
  weight: number | null;
}

/** Mirrors app.discovery.schemas.LandscapeGraphResponse. */
export interface NeuralMapGraph {
  nodes: NeuralMapNode[];
  edges: NeuralMapEdge[];
}

export type ProfileLevel = "beginner" | "intermediate" | "advanced";

/** Mirrors app.discovery.schemas.ProfileUpdateRequest (the write shape —
 * ProfileResponse additionally carries id/created_at/updated_at, which
 * nothing in this UI needs today). */
export interface Profile {
  interests: string[];
  level: ProfileLevel;
  goals: string[];
}

/** Mirrors app.discovery.schemas.RecommendationItem. */
export interface Recommendation {
  arxiv_id: string;
  title: string;
  authors: string[];
  year: number | null;
  abstract: string;
  relevance_score: number;
  explanation: string;
}

export interface GetRecommendationsParams {
  provider_id: string;
  /** Sent as the `X-Provider-Api-Key` header, never a query param — the
   * router deliberately deviates from a plain `?api_key=...` GET because a
   * secret in the URL is trivially captured by access/proxy logs (see
   * app.discovery.router.get_recommendations's comment). */
  api_key?: string;
  endpoint?: string;
  /** Recommendations only ever ranks by embedding similarity -- there is no
   * chat-model field on this request at all. Optional only at the type
   * level: the caller gates dispatch on isSelectionReady(selection, {chat:
   * false, embed: true}) first, so this is always populated in practice. */
  embed_model?: string;
}

const VERIFICATION_STATUSES: readonly string[] = [
  "verified",
  "partially-matched",
  "mismatch",
  "not-found",
  "needs-review",
];

function isVerificationStatus(value: unknown): value is VerificationStatus {
  return typeof value === "string" && VERIFICATION_STATUSES.includes(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function parseExtractedField(value: unknown): ExtractedField | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.text !== "string" || !isVerificationStatus(v.verification_status)) return null;
  return { text: v.text, verification_status: v.verification_status };
}

function parseExtractionCard(value: unknown): PaperExtractionCard | null {
  if (value === null) return null;
  if (typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  const tldr = parseExtractedField(v.tldr);
  const problem = parseExtractedField(v.problem);
  const method = parseExtractedField(v.method);
  const results = parseExtractedField(v.results);
  const whyItMatters = parseExtractedField(v.why_it_matters);
  if (!tldr || !problem || !method || !results || !whyItMatters) return null;
  return { tldr, problem, method, results, why_it_matters: whyItMatters };
}

function parseLandscapePaper(value: unknown): LandscapePaper | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.arxiv_id !== "string" || typeof v.title !== "string") return null;
  if (typeof v.pdf_url !== "string" || typeof v.abstract !== "string") return null;
  if (typeof v.relevance_score !== "number" || !isStringArray(v.authors)) return null;

  let extraction: PaperExtractionCard | null = null;
  if (v.extraction !== undefined && v.extraction !== null) {
    extraction = parseExtractionCard(v.extraction);
    if (extraction === null) return null; // extraction present but malformed -- drop the whole payload
  }

  return {
    arxiv_id: v.arxiv_id,
    title: v.title,
    authors: v.authors,
    year: typeof v.year === "number" ? v.year : null,
    pdf_url: v.pdf_url,
    abstract: v.abstract,
    relevance_score: v.relevance_score,
    cluster_id: typeof v.cluster_id === "string" ? v.cluster_id : null,
    extraction,
  };
}

function parseMethodCluster(value: unknown): MethodCluster | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.id !== "string" || typeof v.label !== "string" || typeof v.description !== "string") return null;
  if (!isStringArray(v.paper_ids)) return null;
  return { id: v.id, label: v.label, description: v.description, paper_ids: v.paper_ids };
}

/**
 * Validates/narrows the streamed `done` event's `data` into a
 * `TopicLandscape`, the same defensive-parsing pattern as
 * `assistant-panel.tsx`'s `parseAssistantResponse` — one malformed field
 * drops the whole payload rather than rendering a partially-typed lie.
 */
export function parseTopicLandscape(data: Record<string, unknown> | null): TopicLandscape | null {
  if (!data) return null;
  const { id, topic, overview, papers, clusters, created_at } = data;
  if (typeof id !== "string" || typeof topic !== "string" || typeof overview !== "string") return null;
  if (typeof created_at !== "string" || !Array.isArray(papers) || !Array.isArray(clusters)) return null;

  const parsedPapers: LandscapePaper[] = [];
  for (const paper of papers) {
    const parsed = parseLandscapePaper(paper);
    if (parsed === null) return null;
    parsedPapers.push(parsed);
  }

  const parsedClusters: MethodCluster[] = [];
  for (const cluster of clusters) {
    const parsed = parseMethodCluster(cluster);
    if (parsed === null) return null;
    parsedClusters.push(parsed);
  }

  return { id, topic, overview, papers: parsedPapers, clusters: parsedClusters, created_at };
}

export function streamLandscape(
  request: DiscoverLandscapeRequest,
  onEvent: (event: AnalysisEvent) => void,
): Promise<void> {
  return streamSse("/discover/landscape", request, onEvent);
}

export function getLandscape(id: string): Promise<TopicLandscape> {
  return apiFetch<TopicLandscape>(`/discover/landscape/${id}`);
}

export function getLandscapeGraph(id: string): Promise<NeuralMapGraph> {
  return apiFetch<NeuralMapGraph>(`/discover/landscape/${id}/graph`);
}

/** Mirrors app.discovery.schemas.LandscapePromoteRequest — exactly one of
 * collection_id/collection_name is meant to be set (existing vs new
 * collection), same "one-of" discipline as RoadmapTarget. */
export interface LandscapePromoteRequest {
  collection_id?: string;
  collection_name?: string;
}

/** Mirrors app.discovery.schemas.LandscapePromoteResponse. `added`/
 * `skipped_not_ingested` are arxiv_id lists, not a plain success flag — a
 * skipped candidate (not yet ingested as an owned Paper) must be surfaced to
 * the user, never silently dropped. */
export interface LandscapePromoteResponse {
  collection_id: string;
  added: string[];
  skipped_not_ingested: string[];
}

export function promoteLandscape(
  landscapeId: string,
  request: LandscapePromoteRequest,
): Promise<LandscapePromoteResponse> {
  return apiFetch<LandscapePromoteResponse>(`/discover/landscape/${landscapeId}/promote`, {
    method: "POST",
    body: request,
  });
}

export function getProfile(): Promise<Profile> {
  return apiFetch<Profile>("/discover/profile");
}

export function updateProfile(profile: Profile): Promise<Profile> {
  return apiFetch<Profile>("/discover/profile", { method: "PUT", body: profile });
}

/** GET /discover/recommendations returns a plain JSON array (`list[RecommendationItem]`),
 * not `{recommendations: [...]}` — mirrors app.discovery.router.get_recommendations exactly. */
export function getRecommendations(params: GetRecommendationsParams): Promise<Recommendation[]> {
  const query = new URLSearchParams({ provider_id: params.provider_id, embed_model: params.embed_model ?? "" });
  if (params.endpoint) query.set("endpoint", params.endpoint);
  return apiFetch<Recommendation[]>(`/discover/recommendations?${query.toString()}`, {
    headers: params.api_key ? { "X-Provider-Api-Key": params.api_key } : undefined,
  });
}

// --- Phase 6: research roadmap / prerequisite graph -------------------------
// Mirrors app.discovery.schemas.{RoadmapTarget,RoadmapCreateRequest,Concept,
// PrerequisiteEdge,Milestone,RoadmapResponse,RoadmapSummary,
// MilestoneUpdateRequest} and app.discovery.router's roadmap routes exactly.

/** Mirrors app.discovery.schemas.RoadmapTarget — a discriminated union on
 * `type`, same tagged-union shape the backend enforces via Pydantic's
 * `Field(discriminator="type")`. */
export type RoadmapTarget = { type: "topic"; topic: string } | { type: "paper"; paper_id: string };

/** Mirrors app.discovery.schemas.RoadmapCreateRequest (DiscoveryProviderConfig
 * + target) -- needs both a chat model (concept grounding) and an embed
 * model (milestone candidate ranking). */
export interface RoadmapCreateRequest {
  target: RoadmapTarget;
  provider_id: string;
  api_key?: string;
  endpoint?: string;
  model?: string;
  embed_model?: string;
}

/** Mirrors app.discovery.schemas.Concept — a grounded prerequisite-graph
 * node. Exactly one of source_paper_id/source_arxiv_id is set. */
export interface Concept {
  id: string;
  name: string;
  description: string;
  source_paper_id: string | null;
  source_arxiv_id: string | null;
  grounding_excerpt: string;
  verification_status: VerificationStatus;
}

/** Mirrors app.discovery.schemas.PrerequisiteEdge. */
export interface PrerequisiteEdge {
  concept_id: string;
  prerequisite_concept_id: string;
}

/** Mirrors app.discovery.schemas.MilestoneStatus. "locked" is system-assigned
 * only — never settable via updateMilestoneStatus, see MilestoneUpdateStatus. */
export type MilestoneStatus = "locked" | "available" | "completed" | "skipped";

/** Mirrors app.discovery.schemas.Milestone. */
export interface Milestone {
  id: string;
  order: number;
  paper_id: string | null;
  arxiv_id: string | null;
  title: string;
  concept_ids: string[];
  status: MilestoneStatus;
}

/** Mirrors app.discovery.schemas.RoadmapResponse. */
export interface Roadmap {
  id: string;
  target_description: string;
  target_paper_id: string | null;
  concepts: Concept[];
  edges: PrerequisiteEdge[];
  milestones: Milestone[];
  overview: string;
  created_at: string;
  updated_at: string;
}

/** Mirrors app.discovery.schemas.RoadmapSummary. */
export interface RoadmapSummary {
  id: string;
  target_description: string;
  created_at: string;
  milestone_count: number;
  completed_count: number;
}

/** Mirrors app.discovery.schemas.MilestoneUpdateRequest.status — "locked" is
 * deliberately excluded there (system-assigned initial state, never set by a
 * user action), so it's excluded here too. */
export type MilestoneUpdateStatus = "completed" | "skipped" | "available";

function isMilestoneStatus(value: unknown): value is MilestoneStatus {
  return value === "locked" || value === "available" || value === "completed" || value === "skipped";
}

function parseConcept(value: unknown): Concept | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.id !== "string" || typeof v.name !== "string" || typeof v.description !== "string") return null;
  if (typeof v.grounding_excerpt !== "string" || !isVerificationStatus(v.verification_status)) return null;
  return {
    id: v.id,
    name: v.name,
    description: v.description,
    source_paper_id: typeof v.source_paper_id === "string" ? v.source_paper_id : null,
    source_arxiv_id: typeof v.source_arxiv_id === "string" ? v.source_arxiv_id : null,
    grounding_excerpt: v.grounding_excerpt,
    verification_status: v.verification_status,
  };
}

function parsePrerequisiteEdge(value: unknown): PrerequisiteEdge | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.concept_id !== "string" || typeof v.prerequisite_concept_id !== "string") return null;
  return { concept_id: v.concept_id, prerequisite_concept_id: v.prerequisite_concept_id };
}

function parseMilestone(value: unknown): Milestone | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.id !== "string" || typeof v.order !== "number" || typeof v.title !== "string") return null;
  if (!isStringArray(v.concept_ids) || !isMilestoneStatus(v.status)) return null;
  return {
    id: v.id,
    order: v.order,
    paper_id: typeof v.paper_id === "string" ? v.paper_id : null,
    arxiv_id: typeof v.arxiv_id === "string" ? v.arxiv_id : null,
    title: v.title,
    concept_ids: v.concept_ids,
    status: v.status,
  };
}

/**
 * Validates/narrows the streamed roadmap `done` event's `data` into a
 * `Roadmap` — same defensive-parsing discipline as `parseTopicLandscape`.
 */
export function parseRoadmap(data: Record<string, unknown> | null): Roadmap | null {
  if (!data) return null;
  const { id, target_description, target_paper_id, concepts, edges, milestones, overview, created_at, updated_at } =
    data;
  if (typeof id !== "string" || typeof target_description !== "string" || typeof overview !== "string") return null;
  if (typeof created_at !== "string" || typeof updated_at !== "string") return null;
  if (!Array.isArray(concepts) || !Array.isArray(edges) || !Array.isArray(milestones)) return null;

  const parsedConcepts: Concept[] = [];
  for (const concept of concepts) {
    const parsed = parseConcept(concept);
    if (parsed === null) return null;
    parsedConcepts.push(parsed);
  }

  const parsedEdges: PrerequisiteEdge[] = [];
  for (const edge of edges) {
    const parsed = parsePrerequisiteEdge(edge);
    if (parsed === null) return null;
    parsedEdges.push(parsed);
  }

  const parsedMilestones: Milestone[] = [];
  for (const milestone of milestones) {
    const parsed = parseMilestone(milestone);
    if (parsed === null) return null;
    parsedMilestones.push(parsed);
  }

  return {
    id,
    target_description,
    target_paper_id: typeof target_paper_id === "string" ? target_paper_id : null,
    concepts: parsedConcepts,
    edges: parsedEdges,
    milestones: parsedMilestones,
    overview,
    created_at,
    updated_at,
  };
}

export function streamRoadmap(request: RoadmapCreateRequest, onEvent: (event: AnalysisEvent) => void): Promise<void> {
  return streamSse("/discover/roadmap", request, onEvent);
}

export function getRoadmap(id: string): Promise<Roadmap> {
  return apiFetch<Roadmap>(`/discover/roadmap/${id}`);
}

export function listRoadmaps(): Promise<RoadmapSummary[]> {
  return apiFetch<RoadmapSummary[]>("/discover/roadmaps");
}

export function updateMilestoneStatus(
  roadmapId: string,
  milestoneId: string,
  status: MilestoneUpdateStatus,
): Promise<Roadmap> {
  return apiFetch<Roadmap>(`/discover/roadmap/${roadmapId}/milestones/${milestoneId}`, {
    method: "PATCH",
    body: { status },
  });
}
