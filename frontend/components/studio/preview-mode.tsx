"use client";

import { useEffect, useMemo, useState } from "react";
import { VisualRenderer } from "@/components/visuals/visual-renderer";
import type { ClaimResponse } from "@/lib/evidence-api";
import type { FigurePlacement } from "@/lib/figure-placement";
import type { PaperResponse } from "@/lib/paper-types";
import type { StorySpec } from "@/lib/story-api";
import { cn } from "@/lib/utils";
import { FigureGrid } from "./figure-card";
import { ClosingBlock, StorySectionCopy } from "./story-section-copy";

const SECTION_ATTR = "data-section-id";
const elementId = (sectionId: string): string => `preview-section-${sectionId}`;

/** The section crossing a band around the middle of the viewport is "active".
 * Without IntersectionObserver (old browsers, jsdom) the first stays active. */
function useActiveSection(ids: readonly string[]): [string | null, (id: string) => void] {
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.isIntersecting ? entry.target.getAttribute(SECTION_ATTR) : null;
          if (id) setActiveId(id);
        }
      },
      { rootMargin: "-40% 0px -55% 0px" },
    );
    for (const id of ids) {
      const element = document.getElementById(elementId(id));
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [ids]);

  const active = activeId !== null && ids.includes(activeId) ? activeId : (ids[0] ?? null);
  return [active, setActiveId];
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

interface PreviewModeProps {
  paperId: string;
  paper: PaperResponse;
  spec: StorySpec;
  claims: readonly ClaimResponse[];
  placement: FigurePlacement;
  selectedClaimId: string | null;
  onSelectClaim: (claimId: string) => void;
}

export function PreviewMode({ paperId, paper, spec, claims, placement, selectedClaimId, onSelectClaim }: PreviewModeProps) {
  const { meta, sections } = spec;
  const ids = useMemo(() => sections.map((s) => s.id), [sections]);
  const [activeId, setActiveId] = useActiveSection(ids);
  const activeIndex = sections.findIndex((s) => s.id === activeId);
  const active = activeIndex >= 0 ? sections[activeIndex] : null;
  const byline = [paper.authors.join(", "), paper.venue, paper.year].filter(Boolean).join(" · ");

  function jumpTo(id: string): void {
    setActiveId(id);
    document.getElementById(elementId(id))?.scrollIntoView?.({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "center" });
  }

  return (
    <div className="flex flex-col gap-10">
      <header className="flex flex-col gap-3 py-6">
        <p className="m-0 text-caption font-semibold uppercase tracking-[0.14em] text-paper-accent">Preview</p>
        <h1 className="m-0 font-display text-display font-medium tracking-tight text-ink">{meta.title || paper.title}</h1>
        {meta.dek && <p className="m-0 max-w-2xl text-body-lg text-ink-soft">{meta.dek}</p>}
        <p className="m-0 text-ui-label text-ink-soft">
          {[byline, meta.reading_time].filter(Boolean).join(" · ")}
        </p>
      </header>

      <div className="grid grid-cols-1 gap-10 min-[980px]:grid-cols-2">
        <ol className="m-0 flex list-none flex-col gap-24 p-0 pb-24">
          {sections.map((section) => (
            <li
              key={section.id}
              id={elementId(section.id)}
              {...{ [SECTION_ATTR]: section.id }}
              aria-current={section.id === activeId ? "true" : undefined}
              className={cn(
                "scroll-mt-24 flex flex-col gap-4",
                section.id === activeId ? "opacity-100" : "opacity-45",
                "motion-safe:transition-opacity motion-safe:duration-300",
              )}
            >
              <StorySectionCopy section={section} claims={claims} selectedClaimId={selectedClaimId} onSelectClaim={onSelectClaim} />
              <div className="flex flex-col gap-3 min-[980px]:hidden">
                {section.visual && <VisualRenderer visual={section.visual} />}
                <FigureGrid paperId={paperId} figures={placement.bySection.get(section.id) ?? []} />
              </div>
            </li>
          ))}
        </ol>

        <aside
          aria-label="Visual for the current section"
          className="sticky top-20 hidden flex-col gap-3 self-start min-[980px]:flex"
        >
          <div
            role="progressbar"
            aria-label="Reading progress"
            aria-valuemin={1}
            aria-valuemax={Math.max(sections.length, 1)}
            aria-valuenow={Math.max(activeIndex + 1, 1)}
            aria-valuetext={`Section ${Math.max(activeIndex + 1, 1)} of ${sections.length}`}
            className="h-1 rounded-full bg-secondary"
          >
            <div
              className="h-full rounded-full bg-paper-accent motion-safe:transition-[width] motion-safe:duration-300"
              style={{ width: `${((Math.max(activeIndex, 0) + 1) / Math.max(sections.length, 1)) * 100}%` }}
            />
          </div>
          <ul aria-label="Sections" className="m-0 flex list-none gap-1.5 p-0">
            {sections.map((section) => (
              <li key={section.id}>
                <button
                  type="button"
                  onClick={() => jumpTo(section.id)}
                  aria-label={`Go to section ${section.index_label}: ${section.title}`}
                  aria-current={section.id === activeId ? "step" : undefined}
                  className={cn(
                    "size-3 rounded-full border border-paper-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-paper-accent",
                    section.id === activeId ? "bg-paper-accent" : "bg-surface",
                  )}
                />
              </li>
            ))}
          </ul>
          {active?.visual && <VisualRenderer key={active.id} visual={active.visual} active />}
          {active && <FigureGrid paperId={paperId} figures={placement.bySection.get(active.id) ?? []} />}
        </aside>
      </div>

      {meta.closing && <ClosingBlock closing={meta.closing} />}
    </div>
  );
}
