import { VerificationBadge } from "@/components/verification-badge";
import type { ExtractedField, LandscapePaper } from "@/lib/discovery-api";

/** One extraction field: text plus the independent verifier's judgment on
 * its supporting excerpt — the same text/icon status badge as claims, never
 * color alone, never a dead-end summary with the uncertainty hidden. */
function CardField({ label, field }: { label: string; field: ExtractedField }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1.5">
        <p className="text-caption font-medium text-muted-foreground">{label}</p>
        <VerificationBadge status={field.verification_status} size="inline" />
      </div>
      <p className="text-body text-foreground">{field.text}</p>
    </div>
  );
}

export interface LandscapePaperCardProps {
  paper: LandscapePaper;
}

/** Per-paper extraction card per docs/UI_UX.md's Discover flow. The
 * abstract is always shown alongside the extracted fields so a claim is one
 * click from its source excerpt, never a dead-end summary. */
export function LandscapePaperCard({ paper }: LandscapePaperCardProps) {
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <a
            href={paper.pdf_url}
            target="_blank"
            rel="noreferrer"
            className="text-h4 font-display font-semibold text-foreground hover:underline"
          >
            {paper.title}
          </a>
          <p className="text-caption text-muted-foreground">
            {paper.authors.join(", ") || "Unknown authors"}
            {paper.year ? ` · ${paper.year}` : ""}
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-muted px-2 py-1 text-caption font-medium text-foreground">
          Relevance {Math.round(paper.relevance_score * 100)}%
        </span>
      </div>

      {paper.extraction ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <CardField label="TL;DR" field={paper.extraction.tldr} />
          <CardField label="Problem" field={paper.extraction.problem} />
          <CardField label="Method" field={paper.extraction.method} />
          <CardField label="Key results" field={paper.extraction.results} />
          <CardField label="Why it matters" field={paper.extraction.why_it_matters} />
        </div>
      ) : (
        <p className="text-body text-muted-foreground">Extraction unavailable for this paper.</p>
      )}

      <details className="text-caption text-muted-foreground">
        <summary className="cursor-pointer text-ui-label text-foreground">Abstract (source excerpt)</summary>
        <p className="mt-1.5 whitespace-pre-wrap font-mono text-mono text-foreground">{paper.abstract}</p>
      </details>
    </li>
  );
}
