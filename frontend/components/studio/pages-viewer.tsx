"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { figureUrl, getPaperPage } from "@/lib/papers-api";
import type { FigureResponse, PageResponse } from "@/lib/paper-types";
import { errorMessage } from "./use-loadable";
import { LabSection } from "./lab-parts";

function PageFigure({ paperId, figure }: { paperId: string; figure: FigureResponse }) {
  const [failed, setFailed] = useState(false);
  const filename = figure.image_path.split("/").pop() ?? figure.image_path;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
      {failed ? (
        <p className="m-0 text-ui-label text-ink-soft">Figure failed to load.</p>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- API-served extracted figure
        <img
          src={figureUrl(paperId, filename)}
          alt={figure.caption ?? `Figure on page ${figure.page}`}
          loading="lazy"
          onError={() => setFailed(true)}
          className="max-w-full rounded-md"
        />
      )}
      {figure.caption && <p className="m-0 text-caption text-ink-soft">{figure.caption}</p>}
    </div>
  );
}

/** The original raw page viewer: parsed text exactly as the quote verifier
 * sees it, plus that page's extracted figures. */
export function PagesViewer({ paperId }: { paperId: string }) {
  const [pageNumber, setPageNumber] = useState(1);
  const [page, setPage] = useState<PageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isLoading = !error && page?.page_number !== pageNumber;

  useEffect(() => {
    let cancelled = false;
    getPaperPage(paperId, pageNumber)
      .then((result) => {
        if (cancelled) return;
        setPage(result);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [paperId, pageNumber]);

  return (
    <LabSection title="Pages" intro="The parsed text of each page, exactly as quotes are verified against it.">
      <div className="flex items-center gap-3">
        <Button type="button" variant="outline" size="sm" disabled={pageNumber <= 1} onClick={() => setPageNumber((n) => Math.max(1, n - 1))}>
          Previous
        </Button>
        <label className="flex items-center gap-2 text-ui-label text-ink">
          Page
          <input
            type="number"
            min={1}
            value={pageNumber}
            onChange={(event) => setPageNumber(Math.max(1, Number(event.target.value) || 1))}
            className="w-16 rounded-md border border-line-dark bg-surface px-2 py-1 text-body text-ink"
          />
        </label>
        <Button type="button" variant="outline" size="sm" onClick={() => setPageNumber((n) => n + 1)}>
          Next
        </Button>
      </div>

      {isLoading && <p className="m-0 text-body text-ink-soft">Loading page…</p>}
      {error && (
        <p role="alert" className="m-0 text-body text-mismatch">
          {error}
        </p>
      )}
      {page && !isLoading && !error && (
        <div className="flex flex-col gap-4">
          <pre className="m-0 whitespace-pre-wrap rounded-xl border border-line bg-surface p-4 font-mono text-mono text-ink">{page.text}</pre>
          {page.figures.length > 0 && (
            <div className="flex flex-col gap-3">
              <h3 className="m-0 font-display text-h3 font-medium text-ink">Figures on this page</h3>
              {page.figures.map((figure, index) => (
                <PageFigure key={`${figure.page}-${index}`} paperId={paperId} figure={figure} />
              ))}
            </div>
          )}
        </div>
      )}
    </LabSection>
  );
}
