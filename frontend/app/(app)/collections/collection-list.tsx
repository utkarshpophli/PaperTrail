"use client";

import Link from "next/link";
import type { Collection } from "@/lib/collections-api";

interface CollectionListProps {
  collections: Collection[] | null;
  error: string | null;
}

/** `GET /collections` results, each linking to its detail view — same
 * loading/empty/error shape as roadmaps' RoadmapList. */
export function CollectionList({ collections, error }: CollectionListProps) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Your collections</h2>

      {error && (
        <p role="alert" className="text-body text-mismatch">
          {error}
        </p>
      )}
      {!collections && !error && (
        <div className="flex min-h-[80px] items-center text-body text-muted-foreground">Loading…</div>
      )}
      {collections && collections.length === 0 && (
        <p className="text-body text-muted-foreground">No collections yet. Create one above.</p>
      )}

      {collections && collections.length > 0 && (
        <ul className="flex flex-col gap-2">
          {collections.map((collection) => (
            <li key={collection.id}>
              <Link
                href={`/collections/${collection.id}`}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-background p-3 hover:bg-muted"
              >
                <span className="text-ui-label font-medium text-foreground">{collection.name}</span>
                <span className="shrink-0 text-caption text-muted-foreground">{collection.paper_ids.length} papers</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
