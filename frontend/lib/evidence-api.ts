/**
 * Mirrors backend/app/evidence/schemas.py's response shapes and
 * backend/app/evidence/router.py's AnalyzeRequest/AnalysisEvent exactly —
 * read from the FastAPI source, not just docs/API_SPEC.md.
 */

import { apiFetch, apiRequest } from "./api-client";
import { ApiRequestError, parseErrorBody } from "./api-types";

export type ClaimKind = "reported-result" | "author-interpretation" | "method" | "background" | "limitation";

/** Matches app/models/claim.py::VerificationStatus — set only by the
 * independent quote-exactness verifier, never by frontend code. */
export type VerificationStatus = "verified" | "partially-matched" | "mismatch" | "not-found" | "needs-review";

export interface SourceReferenceResponse {
  id: string;
  page: number;
  excerpt: string;
  locator: string | null;
}

export interface ClaimResponse {
  id: string;
  statement: string;
  kind: ClaimKind;
  verification_status: VerificationStatus;
  source_refs: SourceReferenceResponse[];
  created_at: string;
}

export interface MetricResponse {
  id: string;
  label: string;
  value: string;
  display_value: string;
  unit: string | null;
  context: string | null;
  source_page: number;
  source_excerpt: string;
}

export interface GlossaryTermResponse {
  id: string;
  term: string;
  definition: string;
  source_page: number | null;
  source_excerpt: string | null;
}

export interface EvidenceResponse {
  paper_id: string;
  thesis: string;
  plain_summary: string;
  research_question: string;
  methods: ClaimResponse[];
  findings: ClaimResponse[];
  limitations: ClaimResponse[];
  claims: ClaimResponse[];
  metrics: MetricResponse[];
  glossary: GlossaryTermResponse[];
}

/** Mirrors backend/app/evidence/schemas.py::GeneratedSectionResponse — the
 * shared shape for both the Deep Report and Technical Appendix. */
export interface GeneratedSectionResponse {
  id: string;
  title: string;
  content: string;
  order: number;
  claim_ids: string[];
  created_at: string;
}

/** One stage's provider/model assignment. Mirrors
 * app.evidence.schemas.StageConfig. */
export interface StageConfig {
  provider_id: string;
  api_key?: string;
  endpoint?: string;
  /** Optional only at the type level for the rare embed-only caller
   * (Discover recommendations) that never needs a chat model at all --
   * every other caller is guaranteed a non-empty value here because
   * lib/provider-selection-store.ts's toStageConfig only omits it when
   * explicitly told the feature doesn't need chat. */
  model?: string;
  embed_model?: string;
}

export type AnalysisStage = "evidence" | "technical" | "report" | "visual";

/** Mirrors app.evidence.router.AnalyzeRequest — a provider/model assignment
 * per requested stage. This is a breaking change from Phase 2's flat
 * `{provider_id, api_key, ...}` body (never released, no callers to
 * preserve). */
export interface AnalyzeRequest {
  stages: Partial<Record<AnalysisStage, StageConfig>>;
}

export type AnalysisEventType = "progress" | "checkpoint" | "warning" | "error" | "done";

export interface AnalysisEvent {
  type: AnalysisEventType;
  stage: string | null;
  message: string | null;
  data: Record<string, unknown> | null;
}

const ANALYSIS_EVENT_TYPES: readonly string[] = ["progress", "checkpoint", "warning", "error", "done"];

function isAnalysisEvent(value: unknown): value is AnalysisEvent {
  if (typeof value !== "object" || value === null) return false;
  const type = (value as { type?: unknown }).type;
  return typeof type === "string" && ANALYSIS_EVENT_TYPES.includes(type);
}

interface SseFrame {
  data: string;
}

/**
 * Splits an accumulated SSE buffer into complete frames (blank-line
 * terminated, per the SSE spec) plus whatever incomplete tail hasn't
 * arrived yet — the caller re-feeds that tail with the next chunk.
 *
 * Only `data:` lines matter: the backend's `event: {type}` line duplicates
 * the `type` field already inside the JSON payload (see
 * backend/app/evidence/router.py::_format_sse_event), so this doesn't parse
 * it separately.
 */
export function splitSseFrames(buffer: string): { frames: SseFrame[]; remainder: string } {
  const blocks = buffer.split("\n\n");
  const remainder = blocks.pop() ?? "";
  const frames: SseFrame[] = [];
  for (const block of blocks) {
    const dataLines = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim());
    if (dataLines.length > 0) frames.push({ data: dataLines.join("\n") });
  }
  return { frames, remainder };
}

/**
 * Parses complete SSE frames out of `buffer` into `AnalysisEvent`s,
 * returning the unparsed remainder to prepend to the next chunk. A frame
 * whose `data:` isn't valid JSON or doesn't match the AnalysisEvent shape is
 * dropped rather than thrown — one malformed frame shouldn't kill the whole
 * stream.
 */
export function extractAnalysisEvents(buffer: string): { events: AnalysisEvent[]; remainder: string } {
  const { frames, remainder } = splitSseFrames(buffer);
  const events: AnalysisEvent[] = [];
  for (const frame of frames) {
    try {
      const parsed: unknown = JSON.parse(frame.data);
      if (isAnalysisEvent(parsed)) events.push(parsed);
    } catch {
      // malformed frame -- skip it, don't kill the stream
    }
  }
  return { events, remainder };
}

/**
 * POSTs `request` to `path` and streams the SSE response, calling `onEvent`
 * for each parsed `AnalysisEvent`. Uses `apiRequest` because `apiFetch` always
 * JSON-parses the full body, which doesn't fit a streamed response. An
 * optional `signal` aborts the request/stream (the pending read rejects with
 * an AbortError, which callers should treat as a user cancel). Shared by
 * `streamAnalysis` (`/analyze`) and `streamAssistant` (`/assistant`) — same
 * SSE format (`event: {type}\ndata: {json}\n\n`) on both routes.
 */
export async function streamSse<TRequest>(
  path: string,
  request: TRequest,
  onEvent: (event: AnalysisEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await apiRequest(path, { method: "POST", body: request, signal });
  if (!response.ok) {
    throw new ApiRequestError(response.status, await parseErrorBody(response));
  }

  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, remainder } = extractAnalysisEvents(buffer);
    buffer = remainder;
    for (const event of events) onEvent(event);
  }
}

export function streamAnalysis(
  paperId: string,
  request: AnalyzeRequest,
  onEvent: (event: AnalysisEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse(`/papers/${paperId}/analyze`, request, onEvent, signal);
}

/** The 8 Research Assistant actions per app.evidence.router.AssistantRequest. */
export type AssistantAction =
  | "understand"
  | "deep-dive"
  | "challenge"
  | "compare"
  | "verify"
  | "implement"
  | "research"
  | "learn";

/** Mirrors app.evidence.router.AssistantRequest. `compare_with` (other paper
 * ids) is required non-empty only when `action === "compare"`, and forbidden
 * otherwise — enforced server-side, mirrored client-side in AssistantPanel. */
export interface AssistantRequest {
  action: AssistantAction;
  question?: string;
  compare_with?: string[];
  provider_id: string;
  api_key?: string;
  endpoint?: string;
  model?: string;
}

/** Shape of the assistant stream's final `done` event's `data`. */
export interface AssistantResponse {
  answer: string;
  claim_ids: string[];
}

export function streamAssistant(
  paperId: string,
  request: AssistantRequest,
  onEvent: (event: AnalysisEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse(`/papers/${paperId}/assistant`, request, onEvent, signal);
}

export function getEvidence(paperId: string): Promise<EvidenceResponse> {
  return apiFetch<EvidenceResponse>(`/papers/${paperId}/evidence`);
}

export function getReport(paperId: string): Promise<GeneratedSectionResponse[]> {
  return apiFetch<GeneratedSectionResponse[]>(`/papers/${paperId}/report`);
}

export function getTechnicalAppendix(paperId: string): Promise<GeneratedSectionResponse[]> {
  return apiFetch<GeneratedSectionResponse[]>(`/papers/${paperId}/technical-appendix`);
}

export function getStory(paperId: string): Promise<GeneratedSectionResponse[]> {
  return apiFetch<GeneratedSectionResponse[]>(`/papers/${paperId}/story`);
}

/** Mirrors backend/app/evidence/schemas.py::QuizQuestionResponse. */
export interface QuizQuestionResponse {
  id: string;
  order: number;
  question: string;
  options: string[] | null;
  correct_answer: string;
  explanation: string;
  claim_ids: string[];
  created_at: string;
}

/** Mirrors backend/app/evidence/schemas.py::DerivationStepResponse. `formula`
 * is inert display text -- never evaluated, never rendered as executable. */
export interface DerivationStepResponse {
  explanation: string;
  formula: string;
  claim_ids: string[];
}

/** Mirrors backend/app/evidence/schemas.py::DerivationResponse. */
export interface DerivationResponse {
  id: string;
  order: number;
  title: string;
  steps: DerivationStepResponse[];
  created_at: string;
}

/** Mirrors backend/app/evidence/schemas.py::InteractiveParameterResponse --
 * slider bounds/default for one named formula parameter. */
export interface InteractiveParameterResponse {
  name: string;
  label: string;
  min: number;
  max: number;
  step: number;
  default: number;
  unit: string | null;
}

/** Mirrors backend/app/evidence/schemas.py::InteractiveResponse. `formula`
 * is a restricted-grammar expression string -- the frontend independently
 * re-parses and validates it (frontend/lib/formula-grammar.ts) rather than
 * trusting that the backend already validated it; it is never eval'd. */
export interface InteractiveResponse {
  id: string;
  title: string;
  description: string;
  parameters: InteractiveParameterResponse[];
  formula: string;
  output_label: string;
  claim_ids: string[];
  created_at: string;
}

/** Mirrors backend/app/evidence/schemas.py::LearningResponse -- the visual
 * stage's bundled primer/application_guide/quiz/derivations/interactives
 * output. */
export interface LearningResponse {
  paper_id: string;
  primer: GeneratedSectionResponse[];
  application_guide: GeneratedSectionResponse[];
  quiz: QuizQuestionResponse[];
  derivations: DerivationResponse[];
  interactives: InteractiveResponse[];
}

export function getLearning(paperId: string): Promise<LearningResponse> {
  return apiFetch<LearningResponse>(`/papers/${paperId}/learning`);
}

/** Plain request/response, not SSE -- one generation call over already-
 * persisted evidence (plus, at most, one best-effort GitHub README fetch),
 * not a multi-stage pipeline with progress to stream. Renders read-only:
 * this never executes anything against the user's linked repository. */
export function generateImplementationPlan(
  paperId: string,
  request: StageConfig,
): Promise<GeneratedSectionResponse[]> {
  return apiFetch<GeneratedSectionResponse[]>(`/papers/${paperId}/implementation-plan`, {
    method: "POST",
    body: request,
  });
}

export function getImplementationPlan(paperId: string): Promise<GeneratedSectionResponse[]> {
  return apiFetch<GeneratedSectionResponse[]>(`/papers/${paperId}/implementation-plan`);
}

export function getClaim(paperId: string, claimId: string): Promise<ClaimResponse> {
  return apiFetch<ClaimResponse>(`/papers/${paperId}/claims/${claimId}`);
}

export function reverifyClaim(paperId: string, claimId: string): Promise<ClaimResponse> {
  return apiFetch<ClaimResponse>(`/papers/${paperId}/claims/${claimId}/reverify`, { method: "POST" });
}
