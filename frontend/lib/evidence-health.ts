/**
 * Client-side evidence health: pure counts over the already-fetched evidence
 * and the claim_ids the generated sections cite. No model call, and
 * deliberately no single overall score -- each figure is shown on its own.
 */

import type { ClaimResponse } from "./evidence-api";

export type SectionSource = "story" | "report" | "technical" | "learning";

export interface CitingSection {
  id: string;
  title: string;
  source: SectionSource;
  claimIds: readonly string[];
}

export type ThinReason = "no-claims" | "single-claim" | "no-verified";

export interface ThinSection {
  section: CitingSection;
  reason: ThinReason;
  claimCount: number;
  verifiedCount: number;
}

export interface EvidenceHealth {
  totalClaims: number;
  verifiedClaims: number;
  /** Distinct pages cited by any source ref, ascending. */
  citedPages: number[];
  /** Uncited pages strictly between the first and last cited page. */
  pageGaps: number[];
  /** Pages in [first, last] -- the span the coverage meter is measured over. */
  pageSpan: number;
  usedClaims: ClaimResponse[];
  unusedClaims: ClaimResponse[];
  thinSections: ThinSection[];
}

/** Only story and report sections are judged for thinness; technical and
 * learning sections still count toward "claims in use". */
const JUDGED_SOURCES: readonly SectionSource[] = ["story", "report"];

export function computeEvidenceHealth(claims: readonly ClaimResponse[], sections: readonly CitingSection[]): EvidenceHealth {
  const byId = new Map(claims.map((claim) => [claim.id, claim]));

  const pages = new Set<number>();
  for (const claim of claims) for (const ref of claim.source_refs) pages.add(ref.page);
  const citedPages = [...pages].sort((a, b) => a - b);
  const first = citedPages[0];
  const last = citedPages[citedPages.length - 1];
  const pageGaps: number[] = [];
  if (first !== undefined && last !== undefined) {
    for (let page = first + 1; page < last; page += 1) if (!pages.has(page)) pageGaps.push(page);
  }

  const usedIds = new Set<string>();
  for (const section of sections) for (const id of section.claimIds) if (byId.has(id)) usedIds.add(id);

  const thinSections: ThinSection[] = [];
  for (const section of sections) {
    if (!JUDGED_SOURCES.includes(section.source)) continue;
    const cited = [...new Set(section.claimIds)].flatMap((id) => {
      const claim = byId.get(id);
      return claim ? [claim] : [];
    });
    const verifiedCount = cited.filter((claim) => claim.verification_status === "verified").length;
    const reason: ThinReason | null =
      cited.length === 0 ? "no-claims" : cited.length === 1 ? "single-claim" : verifiedCount === 0 ? "no-verified" : null;
    if (reason) thinSections.push({ section, reason, claimCount: cited.length, verifiedCount });
  }

  return {
    totalClaims: claims.length,
    verifiedClaims: claims.filter((claim) => claim.verification_status === "verified").length,
    citedPages,
    pageGaps,
    pageSpan: first === undefined || last === undefined ? 0 : last - first + 1,
    usedClaims: claims.filter((claim) => usedIds.has(claim.id)),
    unusedClaims: claims.filter((claim) => !usedIds.has(claim.id)),
    thinSections,
  };
}

export const THIN_REASON_TEXT: Record<ThinReason, string> = {
  "no-claims": "cites no known claims",
  "single-claim": "cites only 1 claim",
  "no-verified": "cites no verified claims",
};
