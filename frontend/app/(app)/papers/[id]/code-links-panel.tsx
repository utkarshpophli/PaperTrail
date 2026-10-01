"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProviderPicker } from "@/components/provider-picker";
import { VerificationBadge } from "@/components/verification-badge";
import { ApiRequestError } from "@/lib/api-types";
import {
  deleteCodeLink,
  getCodeLinks,
  getRepositories,
  linkClaimToCode,
  type CodeLink,
  type Repository,
} from "@/lib/coderesearch-api";
import type { ClaimResponse } from "@/lib/evidence-api";
import { isSelectionReady, toStageConfig, useProviderSelection } from "@/lib/provider-selection-store";
import { markExternalDataSent, markProviderUsed } from "@/lib/session-mode-store";

const LINKABLE_CLAIM_KINDS: ReadonlySet<ClaimResponse["kind"]> = new Set(["method", "reported-result"]);

const CODE_LINK_CAPTION =
  "Shows where matching code appears in the repository; it does not prove the code implements the claim.";
const CODE_LINK_DISCLOSURE =
  "Fetches repository files from GitHub and sends their contents to the selected AI provider.";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

/** Each failure mode worth distinguishing gets its own text; anything else
 * shows the backend's message. Rendered only as React text, never as HTML. */
function linkFailureMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 429) {
      return `You've hit the code-linking rate limit (10 per hour). Try again later. (${error.message})`;
    }
    if (error.code === "claim_not_linkable_to_code") {
      return "Only method and reported-result claims can be linked to code.";
    }
    if (error.code === "repository_not_found") {
      return "That repository is no longer linked to this paper. Re-link it and try again.";
    }
    if (error.code === "claim_not_found") {
      return "That claim no longer exists. Re-run the analysis and try again.";
    }
    if (error.code === "github_repo_not_found") {
      return "GitHub could not find that repository. It may be private, renamed or deleted.";
    }
    if (error.status === 502 && error.code === "github_unavailable") {
      return "GitHub could not be reached, so no code was searched. Try again later.";
    }
  }
  return errorMessage(error);
}

function hasKnownLines(link: CodeLink): boolean {
  return link.verification_status === "verified" || link.verification_status === "partially-matched";
}

function statusLabel(link: CodeLink): string {
  if (link.verification_status === "verified") return "Excerpt found in file";
  if (link.verification_status === "partially-matched") return "Excerpt partly found in file";
  return "Excerpt not found in file: needs review";
}

function CodeLinkItem({ link, onDelete }: { link: CodeLink; onDelete: (id: string) => void }) {
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-background p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="break-all font-mono text-mono text-foreground">
          {link.file_path}
          <span className="text-muted-foreground">
            {hasKnownLines(link) ? ` L${link.start_line}–${link.end_line}` : " · line unknown"}
          </span>
        </p>
        <div className="flex items-center gap-2">
          <VerificationBadge status={link.verification_status} size="inline" />
          <Button type="button" variant="outline" size="sm" onClick={() => onDelete(link.id)}>
            Delete link
          </Button>
        </div>
      </div>
      <p className="text-caption font-medium text-foreground">{statusLabel(link)}</p>
      {/* Repo content and model output are untrusted: plain text only. */}
      <pre className="whitespace-pre-wrap break-words rounded-md border border-border bg-card p-2 font-mono text-mono text-foreground">
        {link.excerpt}
      </pre>
      <p className="whitespace-pre-wrap text-caption text-muted-foreground">{link.explanation}</p>
    </li>
  );
}

interface CodeLinksPanelProps {
  paperId: string;
  claims: ClaimResponse[];
}

// Provider/credential/model come from the shared in-memory selection
// (lib/provider-selection-store.ts); the optional GitHub token lives only in
// local state. Neither is ever persisted.
export function CodeLinksPanel({ paperId, claims }: CodeLinksPanelProps) {
  const [githubToken, setGithubToken] = useState("");

  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [repositoryId, setRepositoryId] = useState("");
  const [links, setLinks] = useState<CodeLink[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const [busyClaimId, setBusyClaimId] = useState<string | null>(null);
  const [errorByClaim, setErrorByClaim] = useState<Record<string, string>>({});
  const [emptyClaimIds, setEmptyClaimIds] = useState<ReadonlySet<string>>(new Set());
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const selection = useProviderSelection();

  useEffect(() => {
    Promise.all([getRepositories(paperId), getCodeLinks(paperId)])
      .then(([repos, existing]) => {
        setRepositories(repos);
        setRepositoryId((current) => current || (repos[0]?.id ?? ""));
        setLinks(existing);
        setLoaded(true);
      })
      .catch((error: unknown) => setLoadError(errorMessage(error)));
  }, [paperId]);

  const selectedProvider = selection.provider;
  const linkableClaims = claims.filter((claim) => LINKABLE_CLAIM_KINDS.has(claim.kind));
  const canSubmit = isSelectionReady(selection) && repositoryId !== "" && busyClaimId === null;

  async function handleFind(claimId: string): Promise<void> {
    if (!selectedProvider || !repositoryId) return;
    setBusyClaimId(claimId);
    setErrorByClaim((current) => ({ ...current, [claimId]: "" }));
    // Two independent egress paths: the AI provider (cloud only) and GitHub
    // (always -- repo files are fetched from api.github.com even with a local model).
    markProviderUsed(selectedProvider);
    markExternalDataSent();
    try {
      const created = await linkClaimToCode(paperId, repositoryId, {
        claim_id: claimId,
        ...toStageConfig(selection),
        ...(githubToken.trim() ? { token: githubToken.trim() } : {}),
      });
      // The backend replaces prior links for the same (repository, claim).
      setLinks((current) => [
        ...current.filter((link) => !(link.claim_id === claimId && link.repository_id === repositoryId)),
        ...created,
      ]);
      setEmptyClaimIds((current) => {
        const next = new Set(current);
        if (created.length === 0) next.add(claimId);
        else next.delete(claimId);
        return next;
      });
    } catch (error: unknown) {
      setErrorByClaim((current) => ({ ...current, [claimId]: linkFailureMessage(error) }));
    } finally {
      setBusyClaimId(null);
    }
  }

  async function handleDelete(codeLinkId: string): Promise<void> {
    setDeleteError(null);
    try {
      await deleteCodeLink(paperId, codeLinkId);
      setLinks((current) => current.filter((link) => link.id !== codeLinkId));
    } catch (error: unknown) {
      setDeleteError(errorMessage(error));
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Claim-to-Code Links</h2>
      <p className="text-caption text-muted-foreground">{CODE_LINK_CAPTION}</p>
      <p className="text-caption font-medium text-foreground">{CODE_LINK_DISCLOSURE}</p>

      {loadError && (
        <p role="alert" className="text-body text-mismatch">
          {loadError}
        </p>
      )}

      {!loaded ? null : repositories.length === 0 ? (
        <p className="text-body text-muted-foreground">Link a repository above to find code for a claim.</p>
      ) : (
        <>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
            <label className="sr-only" htmlFor="code-links-repository">
              Repository
            </label>
            <select
              id="code-links-repository"
              value={repositoryId}
              onChange={(event) => setRepositoryId(event.target.value)}
              disabled={busyClaimId !== null}
              className="rounded-md border border-input bg-background px-2 py-1.5 text-body text-foreground"
            >
              {repositories.map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.owner}/{repo.name}
                </option>
              ))}
            </select>

            <input
              type="password"
              value={githubToken}
              onChange={(event) => setGithubToken(event.target.value)}
              aria-label="GitHub token (optional)"
              placeholder="GitHub token (optional)"
              autoComplete="off"
              disabled={busyClaimId !== null}
              className="w-48 rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
            />
          </div>

          <ProviderPicker disabled={busyClaimId !== null} />

          {deleteError && (
            <p role="alert" className="text-body text-mismatch">
              {deleteError}
            </p>
          )}

          {linkableClaims.length === 0 ? (
            <p className="text-body text-muted-foreground">
              No method or reported-result claims to link. Only those kinds can be matched to code.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {linkableClaims.map((claim) => {
                const claimLinks = links.filter(
                  (link) => link.claim_id === claim.id && link.repository_id === repositoryId,
                );
                const busy = busyClaimId === claim.id;
                return (
                  <li key={claim.id} className="flex flex-col gap-2 rounded-md border border-border bg-background p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex flex-col gap-1">
                        <p className="text-body text-foreground">{claim.statement}</p>
                        <p className="text-caption text-muted-foreground">
                          {claim.kind === "method" ? "Method" : "Reported result"} claim
                        </p>
                      </div>
                      <Button type="button" size="sm" onClick={() => void handleFind(claim.id)} disabled={!canSubmit}>
                        {busy ? "Searching…" : "Find implementing code"}
                      </Button>
                    </div>
                    {errorByClaim[claim.id] && (
                      <p role="alert" className="rounded-md bg-mismatch-bg px-3 py-2 text-body text-mismatch">
                        {errorByClaim[claim.id]}
                      </p>
                    )}
                    {emptyClaimIds.has(claim.id) && claimLinks.length === 0 && (
                      <p className="text-caption text-muted-foreground">
                        No matching code was proposed for this claim in this repository.
                      </p>
                    )}
                    {claimLinks.length > 0 && (
                      <ul className="flex flex-col gap-2">
                        {claimLinks.map((link) => (
                          <CodeLinkItem key={link.id} link={link} onDelete={(id) => void handleDelete(id)} />
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
