"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiRequestError } from "@/lib/api-types";
import { ClaimReferenceList } from "@/components/claim-reference-list";
import { FigureGrid } from "@/components/studio/figure-card";
import type { ClaimResponse, GeneratedSectionResponse } from "@/lib/evidence-api";
import { placeFigures } from "@/lib/figure-placement";
import type { Figure } from "@/lib/story-api";

const NO_FIGURES: readonly Figure[] = [];

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

type SectionsState =
  | { status: "loading" }
  | { status: "not-generated" }
  | { status: "error"; message: string }
  | { status: "ready"; sections: GeneratedSectionResponse[] };

interface GeneratedSectionsPanelProps {
  title: string;
  paperId: string;
  /** The paper's already-fetched evidence claims, used to resolve each
   * section's `claim_ids` back to their statement + source refs -- shared
   * shape between the Deep Report and Technical Appendix (backend/app/
   * evidence/schemas.py::GeneratedSectionResponse), so one component
   * renders both. */
  claims: ClaimResponse[];
  fetchSections: (paperId: string) => Promise<GeneratedSectionResponse[]>;
  notFoundCode: string;
  /** Bumped by the parent after a new analysis run completes, to refetch. */
  refreshKey: number;
  /** "h2" (default) when this is a top-level page section (page.tsx's Deep
   * Report/Technical Appendix); "h3" when a caller nests this inside its own
   * h2 panel (learning-panel.tsx's Primer/Application Guide,
   * implementation-plan-panel.tsx's plan) -- keeps the document's heading
   * outline from skipping/duplicating a level for screen-reader navigation. */
  headingLevel?: "h2" | "h3";
  /** The paper's extracted figures/tables. Each is shown under the section
   * that names it or cites its claims (see placeFigures); omit to show none. */
  figures?: readonly Figure[];
}

export function GeneratedSectionsPanel({
  title,
  paperId,
  claims,
  fetchSections,
  notFoundCode,
  refreshKey,
  headingLevel = "h2",
  figures = NO_FIGURES,
}: GeneratedSectionsPanelProps) {
  const Heading = headingLevel;
  const SectionHeading = headingLevel === "h2" ? "h3" : "h4";
  const [state, setState] = useState<SectionsState>({ status: "loading" });
  const placement = useMemo(
    () =>
      placeFigures(
        state.status === "ready"
          ? state.sections.map((s) => ({ id: s.id, claim_ids: s.claim_ids, text: `${s.title}\n${s.content}` }))
          : [],
        figures,
      ),
    [state, figures],
  );

  useEffect(() => {
    let cancelled = false;
    // ponytail: no synchronous setState({status: "loading"}) here (that's a
    // lint-flagged cascading-render pattern) -- a refetch after refreshKey
    // bumps just leaves the previous sections/state visible until the new
    // fetch resolves, same tradeoff page.tsx's isLoadingPage makes.
    fetchSections(paperId)
      .then((sections) => {
        if (cancelled) return;
        setState({ status: "ready", sections: [...sections].sort((a, b) => a.order - b.order) });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // Not run yet -- a calm empty state, not an alarming error.
        if (error instanceof ApiRequestError && error.code === notFoundCode) {
          setState({ status: "not-generated" });
          return;
        }
        setState({ status: "error", message: errorMessage(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [paperId, fetchSections, notFoundCode, refreshKey]);

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4">
      <Heading className="text-h4 font-display font-semibold text-foreground">{title}</Heading>

      {state.status === "loading" && <p className="text-body text-muted-foreground">Loading…</p>}

      {state.status === "not-generated" && (
        <p className="text-body text-muted-foreground">
          Not generated yet. Select this stage in the Analyze panel above and run analysis.
        </p>
      )}

      {state.status === "error" && (
        <p role="alert" className="text-body text-mismatch">
          {state.message}
        </p>
      )}

      {state.status === "ready" && (
        <ol className="flex flex-col gap-4">
          {state.sections.map((section) => (
            <li key={section.id} className="flex flex-col gap-2 rounded-lg border border-border bg-background p-3">
              <SectionHeading className="text-h4 font-display font-semibold text-foreground">{section.title}</SectionHeading>
              <p className="max-w-[72ch] whitespace-pre-wrap font-sans text-body-lg text-foreground">{section.content}</p>
              <FigureGrid paperId={paperId} figures={placement.bySection.get(section.id) ?? NO_FIGURES} />
              <div className="flex flex-col gap-1">
                <p className="text-caption font-medium text-muted-foreground">Sources</p>
                <ClaimReferenceList claimIds={section.claim_ids} claims={claims} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
