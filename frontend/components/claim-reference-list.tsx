"use client";

import { useState } from "react";
import { VerificationBadge } from "@/components/verification-badge";
import type { ClaimResponse } from "@/lib/evidence-api";

/** Verbatim quotation -- mono font per the "verbatim quotation" visual
 * language, never paraphrased/reformatted. Shared between EvidencePanel's
 * claim rows and any other surface that links back to a claim's sources. */
export function ClaimSourceRefs({ claim }: { claim: ClaimResponse }) {
  return (
    <ul className="flex flex-col gap-2">
      {claim.source_refs.map((ref) => (
        <li key={ref.id} className="rounded-md border border-border bg-background p-3">
          <p className="text-caption text-muted-foreground">
            Page {ref.page}
            {ref.locator ? ` · ${ref.locator}` : ""}
          </p>
          <p className="whitespace-pre-wrap font-mono text-mono text-foreground">&ldquo;{ref.excerpt}&rdquo;</p>
        </li>
      ))}
    </ul>
  );
}

function ClaimReferenceRow({ claim }: { claim: ClaimResponse }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-background p-2">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex items-start justify-between gap-3 text-left"
      >
        <span className="text-caption text-foreground">{claim.statement}</span>
        <VerificationBadge status={claim.verification_status} size="inline" />
      </button>
      {expanded && <ClaimSourceRefs claim={claim} />}
    </li>
  );
}

interface ClaimReferenceListProps {
  /** Claim ids a generated section (report/technical) cites — resolved
   * against `claims` (the paper's already-fetched evidence claims) so every
   * generated section stays click-through-to-source, never a dead-end
   * summary, per docs/UI_UX.md. */
  claimIds: string[];
  claims: ClaimResponse[];
}

export function ClaimReferenceList({ claimIds, claims }: ClaimReferenceListProps) {
  const resolved = claimIds
    .map((id) => claims.find((claim) => claim.id === id))
    .filter((claim): claim is ClaimResponse => claim !== undefined);

  if (resolved.length === 0) {
    return <p className="text-caption text-muted-foreground">Sources unavailable. Re-run evidence to relink.</p>;
  }

  return (
    <ul className="flex flex-col gap-1.5">
      {resolved.map((claim) => (
        <ClaimReferenceRow key={claim.id} claim={claim} />
      ))}
    </ul>
  );
}
