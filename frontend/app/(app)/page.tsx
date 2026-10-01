"use client";

import Link from "next/link";
import { Composer } from "@/components/composer/composer";
import { ParseStatusIndicator } from "@/components/parse-status-indicator";
import { formatCreatedDate } from "@/lib/paper-meta";
import { usePapers } from "@/lib/use-papers";

const RECENT_COUNT = 6;

function RecentPapers() {
  const { papers, loading, error } = usePapers();
  const recent = papers.slice(0, RECENT_COUNT);

  return (
    <section aria-labelledby="recent-papers" className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="recent-papers" className="font-display text-h3 font-medium tracking-tight text-ink">
          Recent papers
        </h2>
        <Link href="/library" className="text-ui-label font-medium text-ink underline-offset-4 hover:underline">
          View library
        </Link>
      </div>

      {error && (
        <p role="alert" className="text-body text-mismatch">
          {error}
        </p>
      )}
      {loading && <p className="text-body text-muted-foreground">Loading…</p>}
      {!loading && !error && recent.length === 0 && (
        <p className="text-body text-muted-foreground">No papers yet. Generate your first one above.</p>
      )}

      <ul className="grid gap-3 sm:grid-cols-2">
        {recent.map((paper) => (
          <li key={paper.id} className="flex flex-col gap-2 rounded-xl border border-line bg-surface px-4 py-3">
            {paper.parse_status === "parsed" ? (
              <Link href={`/papers/${paper.id}`} className="line-clamp-2 text-body font-medium text-ink hover:underline">
                {paper.title}
              </Link>
            ) : (
              <span className="line-clamp-2 text-body font-medium text-ink">{paper.title}</span>
            )}
            <div className="flex items-center justify-between gap-2">
              <ParseStatusIndicator status={paper.parse_status} errorMessage={paper.parse_error} />
              <span className="text-caption text-muted-foreground">{formatCreatedDate(paper.created_at)}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Research Home: the composer (paper + model -> Generate) and recent papers. */
export default function ResearchHomePage() {
  return (
    <div className="flex flex-1 flex-col gap-12 px-4 py-12 sm:px-6">
      <header className="flex max-w-2xl flex-col gap-3">
        <h1 className="font-display text-display font-medium tracking-tight text-ink">Read a paper by its evidence.</h1>
        <p className="text-body-lg text-ink-soft">
          Drop in a paper, choose a model, and Paper Trail extracts every claim with the exact quote and page behind
          it, then builds the report and story around those claims.
        </p>
      </header>
      <Composer />
      <RecentPapers />
    </div>
  );
}
