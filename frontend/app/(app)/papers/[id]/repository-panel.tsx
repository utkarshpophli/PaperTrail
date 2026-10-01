"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api-types";
import {
  deleteRepository,
  detectRepositories,
  getRepositories,
  linkRepository,
  type Repository,
  type RepositoryCandidate,
} from "@/lib/coderesearch-api";
import { markExternalDataSent } from "@/lib/session-mode-store";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

interface RepositoryPanelProps {
  paperId: string;
}

// Token lives only in this component's local state for the duration of a
// request -- never persisted, same in-memory-only-credential rule as every
// other panel's provider/API-key field.
export function RepositoryPanel({ paperId }: RepositoryPanelProps) {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [url, setUrl] = useState("");
  const [linkToken, setLinkToken] = useState("");
  const [linkError, setLinkError] = useState<string | null>(null);
  const [linking, setLinking] = useState(false);

  const [detectToken, setDetectToken] = useState("");
  const [candidates, setCandidates] = useState<RepositoryCandidate[]>([]);
  const [detectError, setDetectError] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [linkingCandidateUrl, setLinkingCandidateUrl] = useState<string | null>(null);

  function refetchRepositories(): void {
    getRepositories(paperId)
      .then((result) => {
        setRepositories(result);
        setLoading(false);
      })
      .catch((error: unknown) => {
        setListError(errorMessage(error));
        setLoading(false);
      });
  }

  useEffect(() => {
    refetchRepositories();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refetchRepositories is stable-enough for a mount-only fetch
  }, [paperId]);

  async function handleLink(candidateUrl?: string): Promise<void> {
    const targetUrl = candidateUrl ?? url;
    if (!targetUrl.trim()) return;
    if (candidateUrl) setLinkingCandidateUrl(candidateUrl);
    else setLinking(true);
    setLinkError(null);
    // The backend fetches repo metadata from api.github.com (with the optional token).
    markExternalDataSent();
    try {
      await linkRepository(paperId, {
        url: targetUrl,
        ...((candidateUrl ? detectToken : linkToken).trim() ? { token: (candidateUrl ? detectToken : linkToken).trim() } : {}),
      });
      if (candidateUrl) {
        setCandidates((current) => current.filter((candidate) => candidate.url !== candidateUrl));
      } else {
        setUrl("");
      }
      refetchRepositories();
    } catch (error: unknown) {
      setLinkError(errorMessage(error));
    } finally {
      setLinking(false);
      setLinkingCandidateUrl(null);
    }
  }

  async function handleUnlink(repositoryId: string): Promise<void> {
    setListError(null);
    try {
      await deleteRepository(paperId, repositoryId);
      setRepositories((current) => current.filter((repo) => repo.id !== repositoryId));
    } catch (error: unknown) {
      setListError(errorMessage(error));
    }
  }

  async function handleDetect(): Promise<void> {
    setDetecting(true);
    setDetectError(null);
    // The backend searches api.github.com using the paper's title/metadata.
    markExternalDataSent();
    try {
      const result = await detectRepositories(paperId, detectToken.trim() ? { token: detectToken.trim() } : {});
      setCandidates(result);
    } catch (error: unknown) {
      setDetectError(errorMessage(error));
    } finally {
      setDetecting(false);
    }
  }

  const linkedUrls = new Set(repositories.map((repo) => repo.url));

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Code Implementation</h2>

      {loading && <p className="text-body text-muted-foreground">Loading…</p>}
      {listError && (
        <p role="alert" className="text-body text-mismatch">
          {listError}
        </p>
      )}

      {!loading && repositories.length === 0 && !listError && (
        <p className="text-body text-muted-foreground">No repository linked yet.</p>
      )}

      {repositories.length > 0 && (
        <ul className="flex flex-col gap-2">
          {repositories.map((repo) => (
            <li
              key={repo.id}
              className="flex items-start justify-between gap-3 rounded-md border border-border bg-background p-3"
            >
              <div className="flex flex-col gap-1">
                <a
                  href={repo.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-ui-label font-medium text-primary hover:underline"
                >
                  {repo.owner}/{repo.name}
                </a>
                {repo.description && <p className="text-caption text-muted-foreground">{repo.description}</p>}
                <p className="text-caption text-muted-foreground">
                  {repo.stars !== null ? `★ ${repo.stars}` : "Star count unavailable"} · Linked
                </p>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={() => void handleUnlink(repo.id)}>
                Unlink
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-2 border-t border-border pt-3">
        <p className="text-ui-label font-medium text-foreground">Link a repository</p>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="sr-only" htmlFor="repo-link-url">
            GitHub URL
          </label>
          <input
            id="repo-link-url"
            type="text"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://github.com/owner/repo"
            disabled={linking}
            className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
          />
          <label className="sr-only" htmlFor="repo-link-token">
            GitHub token (optional)
          </label>
          <input
            id="repo-link-token"
            type="password"
            value={linkToken}
            onChange={(event) => setLinkToken(event.target.value)}
            placeholder="GitHub token (optional)"
            autoComplete="off"
            disabled={linking}
            className="w-48 rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
          />
          <Button type="button" onClick={() => void handleLink()} disabled={!url.trim() || linking}>
            {linking ? "Linking…" : "Link"}
          </Button>
        </div>
        {linkError && (
          <p role="alert" className="text-body text-mismatch">
            {linkError}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2 border-t border-border pt-3">
        <p className="text-ui-label font-medium text-foreground">Detect official implementation</p>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="sr-only" htmlFor="repo-detect-token">
            GitHub token (optional)
          </label>
          <input
            id="repo-detect-token"
            type="password"
            value={detectToken}
            onChange={(event) => setDetectToken(event.target.value)}
            placeholder="GitHub token (optional)"
            autoComplete="off"
            disabled={detecting}
            className="w-48 rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
          />
          <Button type="button" variant="outline" onClick={() => void handleDetect()} disabled={detecting}>
            {detecting ? "Detecting…" : "Detect implementation"}
          </Button>
        </div>
        {detectError && (
          <p role="alert" className="text-body text-mismatch">
            {detectError}
          </p>
        )}

        {candidates.length > 0 && (
          <ul className="flex flex-col gap-2">
            {candidates.map((candidate) => {
              const alreadyLinked = linkedUrls.has(candidate.url);
              return (
                <li
                  key={candidate.url}
                  className="flex items-start justify-between gap-3 rounded-md border border-dashed border-border bg-background p-3"
                >
                  <div className="flex flex-col gap-1">
                    <p className="text-ui-label font-medium text-foreground">
                      {candidate.owner}/{candidate.name}
                    </p>
                    {candidate.description && (
                      <p className="text-caption text-muted-foreground">{candidate.description}</p>
                    )}
                    <p className="text-caption text-muted-foreground">
                      {candidate.stars !== null ? `★ ${candidate.stars}` : "Star count unavailable"} · Unconfirmed
                      guess · Confidence {Math.round(candidate.confidence * 100)}% · Not yet linked
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    disabled={alreadyLinked || linkingCandidateUrl === candidate.url}
                    onClick={() => void handleLink(candidate.url)}
                  >
                    {alreadyLinked ? "Already linked" : linkingCandidateUrl === candidate.url ? "Linking…" : "Link this"}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
