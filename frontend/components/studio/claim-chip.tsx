"use client";

import type { ClaimResponse } from "@/lib/evidence-api";
import { cn } from "@/lib/utils";
import { firstPage } from "./claim-labels";

const STATUS_TEXT: Record<ClaimResponse["verification_status"], string> = {
  verified: "verified",
  "partially-matched": "partial match",
  mismatch: "mismatch",
  "not-found": "not found",
  "needs-review": "needs review",
};

interface ClaimChipProps {
  claim: ClaimResponse;
  selected: boolean;
  onSelect: (claimId: string) => void;
}

/** "Source - p. N" tag. The dot is decoration; verification state is also
 * spelled out in text for anything that is not verified. */
export function ClaimChip({ claim, selected, onSelect }: ClaimChipProps) {
  const page = firstPage(claim);
  const verified = claim.verification_status === "verified";
  return (
    <button
      type="button"
      aria-pressed={selected}
      title={claim.statement}
      onClick={() => onSelect(claim.id)}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-caption font-medium text-ink focus-visible:outline-2 focus-visible:outline-paper-accent",
        selected ? "border-paper-accent bg-muted" : "border-line-dark bg-surface hover:bg-muted",
      )}
    >
      <span aria-hidden="true" className={cn("size-2 rounded-full", verified ? "bg-verified" : "bg-partial")} />
      Source{page !== null ? ` · p. ${page}` : ""}
      {!verified && <span className="text-ink-soft">· {STATUS_TEXT[claim.verification_status]}</span>}
      {verified && <span className="sr-only">, verified</span>}
    </button>
  );
}

interface ClaimChipsProps {
  claimIds: readonly string[];
  claims: readonly ClaimResponse[];
  selectedClaimId: string | null;
  onSelectClaim: (claimId: string) => void;
}

export function ClaimChips({ claimIds, claims, selectedClaimId, onSelectClaim }: ClaimChipsProps) {
  const resolved = [...new Set(claimIds)].flatMap((id) => {
    const claim = claims.find((c) => c.id === id);
    return claim ? [claim] : [];
  });
  if (resolved.length === 0) {
    return <p className="m-0 text-caption text-ink-soft">Sources unavailable. Re-analyze to relink.</p>;
  }
  return (
    <ul aria-label="Sources" className="m-0 flex list-none flex-wrap gap-1.5 p-0">
      {resolved.map((claim) => (
        <li key={claim.id}>
          <ClaimChip claim={claim} selected={claim.id === selectedClaimId} onSelect={onSelectClaim} />
        </li>
      ))}
    </ul>
  );
}
