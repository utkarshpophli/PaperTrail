/**
 * Mirrors backend/app/coderesearch/schemas.py's request/response shapes and
 * backend/app/coderesearch/router.py's routes exactly — read from the
 * FastAPI source, not just docs/API_SPEC.md.
 */

import { apiFetch } from "./api-client";
import type { VerificationStatus } from "./evidence-api";

/** Mirrors app.coderesearch.schemas.RepositoryResponse. A persisted, real
 * row -- `source: "user_linked"` for a manual link, `"detected"` for one a
 * user separately confirmed from a detect-then-link candidate. */
export interface Repository {
  id: string;
  paper_id: string;
  url: string;
  owner: string;
  name: string;
  description: string | null;
  stars: number | null;
  source: "user_linked" | "detected";
  confidence: number | null;
  created_at: string;
}

/** Mirrors app.coderesearch.schemas.RepositoryCandidateResponse. Deliberately
 * has no `id`/`created_at` -- an unpersisted guess from the detect route,
 * never mistaken for a linked `Repository` at the type level. Must be
 * separately confirmed via `linkRepository` to become a real row. */
export interface RepositoryCandidate {
  url: string;
  owner: string;
  name: string;
  description: string | null;
  stars: number | null;
  confidence: number;
}

export interface LinkRepositoryRequest {
  url: string;
  /** Never persisted -- used only for this one metadata fetch. */
  token?: string;
}

export interface DetectRepositoriesRequest {
  token?: string;
}

export function linkRepository(paperId: string, request: LinkRepositoryRequest): Promise<Repository> {
  return apiFetch<Repository>(`/papers/${paperId}/repositories`, { method: "POST", body: request });
}

export function getRepositories(paperId: string): Promise<Repository[]> {
  return apiFetch<Repository[]>(`/papers/${paperId}/repositories`);
}

export function deleteRepository(paperId: string, repositoryId: string): Promise<void> {
  return apiFetch<void>(`/papers/${paperId}/repositories/${repositoryId}`, { method: "DELETE" });
}

export function detectRepositories(
  paperId: string,
  request: DetectRepositoriesRequest,
): Promise<RepositoryCandidate[]> {
  return apiFetch<RepositoryCandidate[]>(`/papers/${paperId}/repositories/detect`, {
    method: "POST",
    body: request,
  });
}

/** Mirrors app.coderesearch.schemas.CodeLinkRequest. `api_key`/`token` are
 * per-request only -- never persisted or logged. */
export interface CodeLinkRequest {
  claim_id: string;
  provider_id: string;
  api_key?: string;
  endpoint?: string;
  model?: string;
  /** Optional GitHub PAT. */
  token?: string;
}

/** Mirrors app.coderesearch.schemas.CodeLinkResponse. `verification_status`
 * means the excerpt occurs in the file text, NOT that the code implements the
 * claim. `start_line`/`end_line` are only meaningful for verified /
 * partially-matched links; other statuses carry a placeholder range. */
export interface CodeLink {
  id: string;
  paper_id: string;
  repository_id: string;
  claim_id: string;
  file_path: string;
  start_line: number;
  end_line: number;
  excerpt: string;
  verification_status: VerificationStatus;
  explanation: string;
  created_at: string;
}

/** Replaces any prior links for the same (repository, claim). */
export function linkClaimToCode(paperId: string, repositoryId: string, request: CodeLinkRequest): Promise<CodeLink[]> {
  return apiFetch<CodeLink[]>(`/papers/${paperId}/repositories/${repositoryId}/code-links`, {
    method: "POST",
    body: request,
  });
}

export function getCodeLinks(paperId: string, claimId?: string): Promise<CodeLink[]> {
  const query = claimId ? `?claim_id=${encodeURIComponent(claimId)}` : "";
  return apiFetch<CodeLink[]>(`/papers/${paperId}/code-links${query}`);
}

export function deleteCodeLink(paperId: string, codeLinkId: string): Promise<void> {
  return apiFetch<void>(`/papers/${paperId}/code-links/${codeLinkId}`, { method: "DELETE" });
}

/** Mirrors the backend's OpenCode handoff response. `markdown` embeds
 * untrusted paper text -- render as plain text only, never as HTML. */
export interface OpencodeHandoff {
  filename: string;
  markdown: string;
  command: string;
}

export function getOpencodeHandoff(paperId: string): Promise<OpencodeHandoff> {
  return apiFetch<OpencodeHandoff>(`/papers/${paperId}/opencode-handoff`);
}
