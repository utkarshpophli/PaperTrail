"use client";

import { ClaimReferenceList } from "@/components/claim-reference-list";
import type { ClaimResponse } from "@/lib/evidence-api";
import type { FigurePlacement } from "@/lib/figure-placement";
import { VisualRenderer } from "@/components/visuals/visual-renderer";
import { FigureGrid } from "./figure-card";
import { ClosingBlock, Paragraphs, StorySectionCopy } from "./story-section-copy";
import type { StoryView } from "./studio-model";

export const STORY_SECTION_ID_PREFIX = "story-section-";

interface StoryModeProps {
  paperId: string;
  paperTitle: string;
  story: StoryView;
  claims: readonly ClaimResponse[];
  placement: FigurePlacement;
  selectedClaimId: string | null;
  onSelectClaim: (claimId: string) => void;
  onGoReanalyze: () => void;
}

export function StoryEmptyState({ onGoReanalyze, message }: { onGoReanalyze: () => void; message?: string }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed border-line-dark bg-surface p-6">
      <h2 className="m-0 font-display text-h3 font-medium text-ink">No story yet</h2>
      <p className="m-0 text-body text-ink-soft">
        {message ?? "This paper has no story. Run the analysis with the story stage selected to generate one."}
      </p>
      <button
        type="button"
        onClick={onGoReanalyze}
        className="rounded-md bg-ink px-3 py-1.5 text-ui-label font-medium text-on-ink focus-visible:outline-2 focus-visible:outline-paper-accent"
      >
        Go to Re-analyze
      </button>
    </div>
  );
}

export function StoryMode({ paperId, paperTitle, story, claims, placement, selectedClaimId, onSelectClaim, onGoReanalyze }: StoryModeProps) {
  if (story.kind === "loading") return <p className="text-body text-ink-soft">Loading story…</p>;
  if (story.kind === "error") {
    return (
      <div className="flex flex-col gap-3">
        <p role="alert" className="m-0 text-body text-mismatch">
          {story.message}
        </p>
        <StoryEmptyState onGoReanalyze={onGoReanalyze} />
      </div>
    );
  }
  if (story.kind === "none") return <StoryEmptyState onGoReanalyze={onGoReanalyze} />;

  if (story.kind === "plain") {
    return (
      <div className="flex flex-col gap-5">
        <header className="flex flex-col gap-2">
          <h1 className="m-0 font-display text-h1 font-medium tracking-tight text-ink">{paperTitle}</h1>
          <p className="m-0 text-ui-label text-ink-soft">
            Text-only story: this analysis predates illustrated stories. Re-analyze to generate visuals.
          </p>
        </header>
        {story.sections.map((section) => (
          <article key={section.id} id={`${STORY_SECTION_ID_PREFIX}${section.id}`} className="flex scroll-mt-24 flex-col gap-3 rounded-xl border border-line bg-surface p-5">
            <h2 className="m-0 font-display text-h3 font-medium tracking-tight text-ink">{section.title}</h2>
            <Paragraphs text={section.content} />
            <ClaimReferenceList claimIds={section.claim_ids} claims={[...claims]} />
          </article>
        ))}
      </div>
    );
  }

  const { meta, sections } = story.spec;
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="m-0 font-display text-h1 font-medium tracking-tight text-ink">{meta.title || paperTitle}</h1>
        {meta.dek && <p className="m-0 text-body-lg text-ink-soft">{meta.dek}</p>}
        {meta.reading_time && <p className="m-0 text-caption font-medium uppercase tracking-wide text-ink-soft">{meta.reading_time}</p>}
      </header>
      {sections.map((section) => (
        <article
          key={section.id}
          id={`${STORY_SECTION_ID_PREFIX}${section.id}`}
          className="flex scroll-mt-24 flex-col gap-4 rounded-xl border border-line bg-surface p-5 sm:p-6"
        >
          <StorySectionCopy section={section} claims={claims} selectedClaimId={selectedClaimId} onSelectClaim={onSelectClaim} />
          {section.visual && <VisualRenderer visual={section.visual} />}
          <FigureGrid paperId={paperId} figures={placement.bySection.get(section.id) ?? []} />
        </article>
      ))}
      {meta.closing && <ClosingBlock closing={meta.closing} />}
    </div>
  );
}
