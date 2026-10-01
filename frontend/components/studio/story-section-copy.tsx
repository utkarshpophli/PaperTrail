import type { ClaimResponse } from "@/lib/evidence-api";
import type { StorySection } from "@/lib/story-api";
import { ClaimChips } from "./claim-chip";

/** Body text arrives as plain text; blank lines separate paragraphs. */
export function Paragraphs({ text, className }: { text: string; className?: string }) {
  return (
    <>
      {text
        .split(/\n{2,}/)
        .map((p) => p.trim())
        .filter(Boolean)
        .map((paragraph, index) => (
          <p key={index} className={className ?? "m-0 text-body-lg text-ink"}>
            {paragraph}
          </p>
        ))}
    </>
  );
}

interface StorySectionCopyProps {
  section: StorySection;
  claims: readonly ClaimResponse[];
  selectedClaimId: string | null;
  onSelectClaim: (claimId: string) => void;
}

/** Index label, kicker, title, body, source chips -- shared by Story cards
 * and the Preview copy column. */
export function StorySectionCopy({ section, claims, selectedClaimId, onSelectClaim }: StorySectionCopyProps) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline gap-3">
        <span className="font-display text-h2 italic leading-none text-paper-accent">{section.index_label}</span>
        <p className="m-0 text-caption font-semibold uppercase tracking-[0.14em] text-ink-soft">{section.kicker}</p>
      </div>
      <h2 className="m-0 font-display text-h2 font-medium tracking-tight text-ink">{section.title}</h2>
      <div className="flex flex-col gap-3">
        <Paragraphs text={section.body} />
      </div>
      <ClaimChips claimIds={section.claim_ids} claims={claims} selectedClaimId={selectedClaimId} onSelectClaim={onSelectClaim} />
    </div>
  );
}

export function ClosingBlock({ closing }: { closing: { title: string; body: string } }) {
  return (
    <section aria-label="Closing" className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-6">
      {closing.title && <h2 className="m-0 font-display text-h3 font-medium tracking-tight text-ink">{closing.title}</h2>}
      <Paragraphs text={closing.body} />
    </section>
  );
}
