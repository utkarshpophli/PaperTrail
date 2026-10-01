"use client";

import { useMemo, type ReactNode } from "react";
import { computeEvidenceHealth, THIN_REASON_TEXT, type CitingSection } from "@/lib/evidence-health";
import type { ClaimResponse } from "@/lib/evidence-api";
import { Card, LabSection, Meter } from "./lab-parts";

interface LabHealthProps {
  claims: readonly ClaimResponse[];
  sections: readonly CitingSection[];
  onSelectClaim: (claimId: string) => void;
}

function Stat({ title, figure, children }: { title: string; figure: string; children: ReactNode }) {
  return (
    <Card className="flex flex-col gap-2">
      <h3 className="m-0 text-caption font-semibold uppercase tracking-[0.14em] text-ink-soft">{title}</h3>
      <p className="m-0 font-display text-h2 font-medium leading-none tracking-tight text-ink">{figure}</p>
      {children}
    </Card>
  );
}

const SOURCE_LABEL: Record<CitingSection["source"], string> = {
  story: "Story",
  report: "Report",
  technical: "Technical",
  learning: "Learning",
};

/** Computed in the browser from the evidence and the sections' claim_ids --
 * no model call, and deliberately no single overall score. */
export function LabHealth({ claims, sections, onSelectClaim }: LabHealthProps) {
  const health = useMemo(() => computeEvidenceHealth(claims, sections), [claims, sections]);

  if (health.totalClaims === 0) {
    return (
      <LabSection title="Evidence health">
        <p className="m-0 text-body text-ink-soft">There are no claims to assess yet.</p>
      </LabSection>
    );
  }

  const first = health.citedPages[0];
  const last = health.citedPages[health.citedPages.length - 1];

  return (
    <LabSection title="Evidence health" intro="Counts computed in your browser from the extracted evidence. No model is involved.">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Stat title="Verified claims" figure={`${health.verifiedClaims} / ${health.totalClaims}`}>
          <Meter value={health.verifiedClaims} max={health.totalClaims} label="Verified claims" />
          <p className="m-0 text-ui-label text-ink-soft">Quotes confirmed verbatim against the parsed page text.</p>
        </Stat>

        <Stat title="Pages cited" figure={`${health.citedPages.length} page${health.citedPages.length === 1 ? "" : "s"}`}>
          <Meter value={health.citedPages.length} max={health.pageSpan} label="Pages cited within the cited range" />
          <p className="m-0 text-ui-label text-ink-soft">
            {health.pageGaps.length === 0
              ? `No gaps between pages ${first} and ${last}.`
              : `Uncited pages between ${first} and ${last}: ${health.pageGaps.join(", ")}.`}
          </p>
        </Stat>

        <Stat title="Claims in use" figure={`${health.usedClaims.length} / ${health.totalClaims}`}>
          <Meter value={health.usedClaims.length} max={health.totalClaims} label="Claims cited by a story, report, technical or learning section" />
          <p className="m-0 text-ui-label text-ink-soft">
            {sections.length === 0
              ? "No story, report or learning sections exist yet, so every claim counts as unused."
              : `${health.unusedClaims.length} unused.`}
          </p>
          {health.unusedClaims.length > 0 && (
            <ul aria-label="Unused claims" className="m-0 flex max-h-56 list-none flex-col gap-1 overflow-y-auto p-0">
              {health.unusedClaims.map((claim) => (
                <li key={claim.id}>
                  <button
                    type="button"
                    onClick={() => onSelectClaim(claim.id)}
                    className="w-full rounded-md border border-line px-2 py-1 text-left text-ui-label text-ink hover:bg-muted focus-visible:outline-2 focus-visible:outline-paper-accent"
                  >
                    {claim.statement}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Stat>

        <Stat title="Thin sections" figure={String(health.thinSections.length)}>
          <p className="m-0 text-ui-label text-ink-soft">
            Story or report sections that cite one claim or fewer, or no verified claim.
          </p>
          {health.thinSections.length === 0 ? (
            <p className="m-0 text-ui-label text-ink">No thin sections.</p>
          ) : (
            <ul aria-label="Thin sections" className="m-0 flex list-none flex-col gap-1 p-0 text-ui-label text-ink">
              {health.thinSections.map(({ section, reason, claimCount, verifiedCount }) => (
                <li key={section.id}>
                  <span className="font-semibold">{SOURCE_LABEL[section.source]} · {section.title}</span>
                  : {THIN_REASON_TEXT[reason]} ({claimCount} cited, {verifiedCount} verified)
                </li>
              ))}
            </ul>
          )}
        </Stat>
      </div>
    </LabSection>
  );
}
