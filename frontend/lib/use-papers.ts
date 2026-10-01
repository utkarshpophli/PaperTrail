"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiRequestError } from "./api-types";
import type { PaperResponse } from "./paper-types";
import { deletePaper, getPaper, getPapers } from "./papers-api";

const POLL_INTERVAL_MS = 2000;

function messageOf(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof Error) return error.message;
  return "Something went wrong.";
}

/** Newest first; created_at is ISO-8601 so string order is time order. */
function newestFirst(papers: PaperResponse[]): PaperResponse[] {
  return [...papers].sort((a, b) => b.created_at.localeCompare(a.created_at));
}

/** The user's papers, kept fresh while any is still pending/parsing. */
export function usePapers(): {
  papers: PaperResponse[];
  loading: boolean;
  error: string | null;
  remove: (paperId: string) => Promise<void>;
} {
  const [papers, setPapers] = useState<PaperResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPapers()
      .then((loaded) => {
        if (!cancelled) setPapers(newestFirst(loaded));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(messageOf(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const pending = papers.filter((p) => p.parse_status === "pending" || p.parse_status === "parsing");
    if (pending.length === 0) return;
    const interval = setInterval(() => {
      pending.forEach((paper) => {
        getPaper(paper.id)
          .then((updated) => setPapers((current) => current.map((p) => (p.id === updated.id ? updated : p))))
          .catch(() => {
            // Transient poll failure: the next tick retries, no banner per dropped poll.
          });
      });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [papers]);

  const remove = useCallback(async (paperId: string): Promise<void> => {
    try {
      await deletePaper(paperId);
      setPapers((current) => current.filter((p) => p.id !== paperId));
    } catch (err: unknown) {
      setError(messageOf(err));
    }
  }, []);

  return { papers, loading, error, remove };
}
