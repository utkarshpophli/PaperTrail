"use client";

import { VerificationBadge } from "@/components/verification-badge";
import type { ClaimResponse } from "@/lib/evidence-api";
import { cn } from "@/lib/utils";
import { KIND_LABEL, firstPage } from "./claim-labels";
import { EmptyNote, LabSection } from "./lab-parts";

interface LabClaimsProps {
  claims: readonly ClaimResponse[];
  selectedClaimId: string | null;
  onSelectClaim: (claimId: string) => void;
}

/** Evidence ledger: every claim, its verifier status and page. The row id is
 * the `#claim-<id>` permalink target. */
export function LabClaims({ claims, selectedClaimId, onSelectClaim }: LabClaimsProps) {
  const verified = claims.filter((c) => c.verification_status === "verified").length;
  return (
    <LabSection title="Claims" intro="Every claim the analysis extracted, with the independent verifier's verdict on its quote.">
      <p className="m-0 text-ui-label font-semibold text-ink" aria-live="polite">
        {verified}/{claims.length} verified
      </p>
      {claims.length === 0 ? (
        <EmptyNote>No claims were extracted.</EmptyNote>
      ) : (
        <ul aria-label="Claims ledger" className="m-0 flex list-none flex-col gap-2 p-0">
          {claims.map((claim) => {
            const page = firstPage(claim);
            return (
              <li key={claim.id} id={`claim-${claim.id}`} className="group relative scroll-mt-24">
                <button
                  type="button"
                  onClick={() => onSelectClaim(claim.id)}
                  aria-pressed={claim.id === selectedClaimId}
                  className={cn(
                    "grid w-full grid-cols-[1fr_auto] items-start gap-x-3 gap-y-1 rounded-lg border bg-surface p-3 pr-8 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-paper-accent",
                    claim.id === selectedClaimId ? "border-paper-accent" : "border-line",
                  )}
                >
                  <span className="text-caption font-semibold uppercase tracking-wide text-ink-soft">{KIND_LABEL[claim.kind]}</span>
                  <span className="row-span-2 flex flex-col items-end gap-1">
                    <VerificationBadge status={claim.verification_status} size="inline" />
                    {page !== null && <span className="text-caption text-ink-soft">p. {page}</span>}
                  </span>
                  <span className="text-body text-ink">{claim.statement}</span>
                </button>
                <a
                  href={`#claim-${claim.id}`}
                  aria-label={`Permalink to claim: ${claim.statement}`}
                  className="absolute right-2 top-2 rounded px-1 text-ui-label text-ink-soft opacity-0 hover:text-paper-accent focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-paper-accent group-hover:opacity-100"
                >
                  #
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </LabSection>
  );
}
