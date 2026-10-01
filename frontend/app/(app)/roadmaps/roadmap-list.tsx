"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiRequestError } from "@/lib/api-types";
import { listRoadmaps, type RoadmapSummary } from "@/lib/discovery-api";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Could not load roadmaps.";
}

/** `GET /discover/roadmaps` — the user's existing roadmaps, each linking to
 * its detail view. */
export function RoadmapList() {
  const [roadmaps, setRoadmaps] = useState<RoadmapSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRoadmaps()
      .then(setRoadmaps)
      .catch((err: unknown) => setError(errorMessage(err)));
  }, []);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Your roadmaps</h2>

      {error && (
        <p role="alert" className="text-body text-mismatch">
          {error}
        </p>
      )}
      {!roadmaps && !error && (
        <div className="flex min-h-[80px] items-center text-body text-muted-foreground">Loading…</div>
      )}
      {roadmaps && roadmaps.length === 0 && (
        <p className="text-body text-muted-foreground">No roadmaps yet. Create one above.</p>
      )}

      {roadmaps && roadmaps.length > 0 && (
        <ul className="flex flex-col gap-2">
          {roadmaps.map((roadmap) => (
            <li key={roadmap.id}>
              <Link
                href={`/roadmaps/${roadmap.id}`}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-background p-3 hover:bg-muted"
              >
                <span className="text-ui-label font-medium text-foreground">{roadmap.target_description}</span>
                <span className="shrink-0 text-caption text-muted-foreground">
                  {roadmap.completed_count}/{roadmap.milestone_count} milestones
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
