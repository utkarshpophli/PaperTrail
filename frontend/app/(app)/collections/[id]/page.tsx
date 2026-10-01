"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api-types";
import { getCollection, removePaperFromCollection, type Collection } from "@/lib/collections-api";
import { getPapers } from "@/lib/papers-api";
import type { PaperResponse } from "@/lib/paper-types";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Could not load collection.";
}

export default function CollectionDetailPage() {
  const params = useParams<{ id: string }>();
  const collectionId = typeof params.id === "string" ? params.id : "";
  const [collection, setCollection] = useState<Collection | null>(null);
  const [papersById, setPapersById] = useState<Map<string, PaperResponse> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  useEffect(() => {
    if (!collectionId) return;
    let cancelled = false;
    // getPapers() already returns the user's full library — reusing it
    // avoids a per-paper fetch for each id in the collection.
    Promise.all([getCollection(collectionId), getPapers()])
      .then(([loadedCollection, papers]) => {
        if (cancelled) return;
        setCollection(loadedCollection);
        setPapersById(new Map(papers.map((paper) => [paper.id, paper])));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [collectionId]);

  async function handleRemove(paperId: string): Promise<void> {
    if (!collection) return;
    setRemovingId(paperId);
    try {
      const updated = await removePaperFromCollection(collection.id, paperId);
      setCollection(updated);
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setRemovingId(null);
    }
  }

  if (error) {
    return (
      <div className="p-6">
        <p role="alert" className="text-body text-mismatch">
          {error}
        </p>
      </div>
    );
  }

  if (!collection || !papersById) {
    return (
      <div className="flex min-h-[200px] items-center justify-center p-6 text-body text-muted-foreground">
        Loading collection…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-h1 font-display font-semibold text-foreground">{collection.name}</h1>
        <Link href="/graph" className="text-ui-label font-medium text-primary hover:underline">
          View in graph
        </Link>
      </div>

      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
        <h2 className="text-h4 font-display font-semibold text-foreground">Papers</h2>

        {collection.paper_ids.length === 0 && (
          <p className="text-body text-muted-foreground">No papers in this collection yet.</p>
        )}

        {collection.paper_ids.length > 0 && (
          <ul className="flex flex-col gap-2">
            {collection.paper_ids.map((paperId) => {
              const paper = papersById.get(paperId);
              return (
                <li
                  key={paperId}
                  className="flex items-center justify-between gap-3 rounded-md border border-border bg-background p-3"
                >
                  {paper ? (
                    <Link href={`/papers/${paper.id}`} className="text-ui-label font-medium text-foreground hover:underline">
                      {paper.title}
                    </Link>
                  ) : (
                    <span className="text-ui-label text-muted-foreground">Paper no longer available</span>
                  )}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void handleRemove(paperId)}
                    disabled={removingId === paperId}
                  >
                    {removingId === paperId ? "Removing…" : "Remove"}
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
