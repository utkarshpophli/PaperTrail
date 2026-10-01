"use client";

import type { EvidenceResponse } from "@/lib/evidence-api";
import type { Figure } from "@/lib/story-api";
import { FigureGrid } from "./figure-card";
import { Card, ClaimButtonList, EmptyNote, LabSection } from "./lab-parts";

interface LabOverviewProps {
  paperId: string;
  evidence: EvidenceResponse;
  unplacedFigures: readonly Figure[];
  figuresError: string | null;
  selectedClaimId: string | null;
  onSelectClaim: (claimId: string) => void;
}

export function LabOverview({ paperId, evidence, unplacedFigures, figuresError, selectedClaimId, onSelectClaim }: LabOverviewProps) {
  return (
    <LabSection>
      <Card className="flex flex-col gap-2">
        <p className="m-0 text-caption font-semibold uppercase tracking-[0.14em] text-paper-accent">Thesis</p>
        <p className="m-0 max-w-[60ch] font-display text-h3 font-medium tracking-tight text-ink">{evidence.thesis}</p>
      </Card>

      <div className="flex flex-col gap-4">
        <Card className="flex flex-col gap-1">
          <h3 className="m-0 text-caption font-semibold uppercase tracking-[0.14em] text-ink-soft">Research question</h3>
          <p className="m-0 max-w-[72ch] text-body-lg text-ink">{evidence.research_question}</p>
        </Card>
        <Card className="flex flex-col gap-1">
          <h3 className="m-0 text-caption font-semibold uppercase tracking-[0.14em] text-ink-soft">In plain words</h3>
          <p className="m-0 max-w-[72ch] text-body-lg text-ink">{evidence.plain_summary}</p>
        </Card>
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="m-0 font-display text-h3 font-medium text-ink">Key findings</h3>
        {evidence.findings.length === 0 ? (
          <EmptyNote>No findings were extracted.</EmptyNote>
        ) : (
          <ClaimButtonList
            label="Key findings"
            claims={evidence.findings}
            numbered
            selectedClaimId={selectedClaimId}
            onSelectClaim={onSelectClaim}
          />
        )}
      </div>

      {figuresError && (
        <p role="alert" className="m-0 text-caption text-mismatch">
          Figures unavailable: {figuresError}
        </p>
      )}
      {unplacedFigures.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="m-0 font-display text-h3 font-medium text-ink">Figures not used in the story</h3>
          <FigureGrid paperId={paperId} figures={unplacedFigures} />
        </div>
      )}
    </LabSection>
  );
}
