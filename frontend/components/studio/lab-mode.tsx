"use client";

import { useCallback } from "react";
import { AnalyzePanel } from "@/app/(app)/papers/[id]/analyze-panel";
import { AssistantPanel } from "@/app/(app)/papers/[id]/assistant-panel";
import { CitationsPanel } from "@/app/(app)/papers/[id]/citations-panel";
import { GeneratedSectionsPanel } from "@/app/(app)/papers/[id]/generated-sections-panel";
import { LearningPanel } from "@/app/(app)/papers/[id]/learning-panel";
import { getReport, getTechnicalAppendix, type EvidenceResponse, type LearningResponse } from "@/lib/evidence-api";
import type { CitingSection } from "@/lib/evidence-health";
import type { Figure } from "@/lib/story-api";
import { LAB_SECTIONS, type LabSectionId } from "./lab-sections";
import { LabClaims } from "./lab-claims";
import { LabGlossary } from "./lab-glossary";
import { LabHealth } from "./lab-health";
import { LabMetrics } from "./lab-metrics";
import { LabOverview } from "./lab-overview";
import { ClaimButtonList, EmptyNote, LabSection } from "./lab-parts";
import { PagesViewer } from "./pages-viewer";
import type { Loadable } from "./use-loadable";

export function NotAnalyzed({ paperId, onAnalysisDone }: { paperId: string; onAnalysisDone: () => void }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-dashed border-line-dark bg-surface p-6">
        <h2 className="m-0 font-display text-h3 font-medium text-ink">Not analyzed yet</h2>
        <p className="mt-1 mb-0 text-body text-ink-soft">
          Run the analysis to extract claims, verify their quotes against the pages, and build the story.
        </p>
      </div>
      <AnalyzePanel paperId={paperId} onAnalysisDone={onAnalysisDone} />
    </div>
  );
}

function PrimerSection({
  paperId,
  evidence,
  learning,
  refreshKey,
  figures,
}: {
  paperId: string;
  evidence: EvidenceResponse;
  learning: Loadable<LearningResponse>;
  refreshKey: number;
  figures: readonly Figure[];
}) {
  const primer = learning.status === "ready" ? learning.data.primer : null;
  const fetchPrimer = useCallback(() => Promise.resolve(primer ?? []), [primer]);
  if (learning.status === "loading") return <EmptyNote>Loading…</EmptyNote>;
  if (!primer) {
    return <EmptyNote>{learning.status === "error" ? learning.message : "No primer yet. Re-analyze with the learning stage selected."}</EmptyNote>;
  }
  return (
    <GeneratedSectionsPanel
      title="Primer"
      paperId={paperId}
      claims={evidence.claims}
      fetchSections={fetchPrimer}
      notFoundCode="learning_not_found"
      refreshKey={refreshKey}
      figures={figures}
    />
  );
}

interface LabModeProps {
  section: LabSectionId;
  paperId: string;
  evidence: EvidenceResponse | null;
  refreshKey: number;
  learning: Loadable<LearningResponse>;
  healthSections: readonly CitingSection[];
  /** Every extracted figure/table, placed inline in Primer/Report/Technical. */
  figures: readonly Figure[];
  unplacedFigures: readonly Figure[];
  figuresError: string | null;
  selectedClaimId: string | null;
  onSelectClaim: (claimId: string) => void;
  onAnalysisDone: () => void;
}

export function LabMode(props: LabModeProps) {
  const { section, paperId, evidence, refreshKey, selectedClaimId, onSelectClaim, onAnalysisDone } = props;
  const needsEvidence = LAB_SECTIONS.find((s) => s.id === section)?.needsEvidence ?? false;

  if (!evidence && needsEvidence) return <NotAnalyzed paperId={paperId} onAnalysisDone={onAnalysisDone} />;

  switch (section) {
    case "citations":
      return <CitationsPanel paperId={paperId} />;
    case "pages":
      return <PagesViewer paperId={paperId} />;
    case "reanalyze":
      return <AnalyzePanel paperId={paperId} onAnalysisDone={onAnalysisDone} />;
  }
  if (!evidence) return null;

  switch (section) {
    case "overview":
      return (
        <LabOverview
          paperId={paperId}
          evidence={evidence}
          unplacedFigures={props.unplacedFigures}
          figuresError={props.figuresError}
          selectedClaimId={selectedClaimId}
          onSelectClaim={onSelectClaim}
        />
      );
    case "primer":
      return <PrimerSection paperId={paperId} evidence={evidence} learning={props.learning} refreshKey={refreshKey} figures={props.figures} />;
    case "learn":
      return <LearningPanel paperId={paperId} claims={evidence.claims} refreshKey={refreshKey} />;
    case "report":
      return (
        <GeneratedSectionsPanel
          title="Deep report"
          paperId={paperId}
          claims={evidence.claims}
          fetchSections={getReport}
          notFoundCode="report_not_found"
          refreshKey={refreshKey}
          figures={props.figures}
        />
      );
    case "technical":
      return (
        <GeneratedSectionsPanel
          title="Technical appendix"
          paperId={paperId}
          claims={evidence.claims}
          fetchSections={getTechnicalAppendix}
          notFoundCode="technical_appendix_not_found"
          refreshKey={refreshKey}
          figures={props.figures}
        />
      );
    case "claims":
      return <LabClaims claims={evidence.claims} selectedClaimId={selectedClaimId} onSelectClaim={onSelectClaim} />;
    case "health":
      return <LabHealth claims={evidence.claims} sections={props.healthSections} onSelectClaim={onSelectClaim} />;
    case "method":
    case "limitations": {
      const claims = section === "method" ? evidence.methods : evidence.limitations;
      const title = section === "method" ? "Method" : "Limitations";
      return (
        <LabSection title={title}>
          {claims.length === 0 ? (
            <EmptyNote>Nothing was extracted for this section.</EmptyNote>
          ) : (
            <ClaimButtonList label={title} claims={claims} selectedClaimId={selectedClaimId} onSelectClaim={onSelectClaim} />
          )}
        </LabSection>
      );
    }
    case "metrics":
      return <LabMetrics metrics={evidence.metrics} claims={evidence.claims} onSelectClaim={onSelectClaim} />;
    case "glossary":
      return <LabGlossary glossary={evidence.glossary} />;
    case "ask":
      return <AssistantPanel paperId={paperId} />;
  }
}
