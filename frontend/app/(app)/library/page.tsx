"use client";

import { useState } from "react";
import Link from "next/link";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ParseStatusIndicator } from "@/components/parse-status-indicator";
import { formatCreatedDate, matchesQuery, summarizeAuthors } from "@/lib/paper-meta";
import type { PaperResponse } from "@/lib/paper-types";
import { usePapers } from "@/lib/use-papers";

interface PaperCardProps {
  paper: PaperResponse;
  confirming: boolean;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}

function PaperCard({ paper, confirming, onAskDelete, onCancelDelete, onConfirmDelete }: PaperCardProps) {
  return (
    <li className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-col gap-1">
        {/* The studio can open a paper at any parse state, so the whole title always links. */}
        <Link href={`/papers/${paper.id}`} className="line-clamp-3 font-display text-h4 font-medium tracking-tight text-ink hover:underline">
          {paper.title}
        </Link>
        <p className="text-ui-label text-ink-soft">{summarizeAuthors(paper.authors)}</p>
        <p className="text-caption text-muted-foreground">
          {[paper.year, paper.venue].filter(Boolean).join(" · ") || "Year unknown"}
        </p>
      </div>

      <ParseStatusIndicator status={paper.parse_status} errorMessage={paper.parse_error} className="self-start" />

      <div className="mt-auto flex items-center justify-between gap-2">
        <span className="text-caption text-muted-foreground">Added {formatCreatedDate(paper.created_at)}</span>
        {confirming ? (
          <div className="flex items-center gap-1" role="group" aria-label={`Confirm deleting ${paper.title}`}>
            <span className="text-caption text-mismatch">Delete this paper?</span>
            <Button type="button" variant="destructive" size="sm" onClick={onConfirmDelete}>
              Delete
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={onCancelDelete}>
              Keep
            </Button>
          </div>
        ) : (
          <Button type="button" variant="ghost" size="icon" aria-label={`Delete ${paper.title}`} onClick={onAskDelete}>
            <Trash2 className="text-destructive" />
          </Button>
        )}
      </div>
    </li>
  );
}

/** Every paper as a card grid: search by title/author, delete with confirmation. */
export default function LibraryPage() {
  const { papers, loading, error, remove } = usePapers();
  const [query, setQuery] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const visible = papers.filter((paper) => matchesQuery(paper, query));

  return (
    <div className="flex flex-1 flex-col gap-8 px-4 py-12 sm:px-6">
      <header className="flex flex-col gap-2">
        <h1 className="font-display text-h1 font-medium tracking-tight text-ink">Library</h1>
        <p className="text-body text-ink-soft">Every paper you have added. Open one to see its claims and evidence.</p>
      </header>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <label className="flex w-full max-w-md flex-col gap-1 text-ui-label font-medium text-ink" htmlFor="library-search">
          Search papers
          <input
            id="library-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Title or author"
            className="rounded-md border border-input bg-background px-3 py-2 text-body font-normal text-ink"
          />
        </label>
        <Button asChild>
          <Link href="/">New paper</Link>
        </Button>
      </div>

      {error && (
        <p role="alert" className="text-body text-mismatch">
          {error}
        </p>
      )}
      {loading && <p className="text-body text-muted-foreground">Loading…</p>}
      {!loading && papers.length === 0 && !error && (
        <p className="text-body text-muted-foreground">No papers yet. Add one from Home.</p>
      )}
      {!loading && papers.length > 0 && visible.length === 0 && (
        <p className="text-body text-muted-foreground">No papers match &quot;{query.trim()}&quot;.</p>
      )}

      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {visible.map((paper) => (
          <PaperCard
            key={paper.id}
            paper={paper}
            confirming={confirmingId === paper.id}
            onAskDelete={() => setConfirmingId(paper.id)}
            onCancelDelete={() => setConfirmingId(null)}
            onConfirmDelete={() => {
              setConfirmingId(null);
              void remove(paper.id);
            }}
          />
        ))}
      </ul>
    </div>
  );
}
