"use client";

import type { ReactNode } from "react";
import { VerificationBadge } from "@/components/verification-badge";
import type { ClaimResponse } from "@/lib/evidence-api";
import { cn } from "@/lib/utils";
import { firstPage } from "./claim-labels";

interface LabSectionProps {
  /** Omit when the wrapped panel already renders its own heading. */
  title?: string;
  intro?: string;
  children: ReactNode;
}

export function LabSection({ title, intro, children }: LabSectionProps) {
  return (
    <section className="flex flex-col gap-4">
      {title && (
        <header className="flex flex-col gap-1">
          <h2 className="m-0 font-display text-h2 font-medium tracking-tight text-ink">{title}</h2>
          {intro && <p className="m-0 text-body text-ink-soft">{intro}</p>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("rounded-xl border border-line bg-surface p-4", className)}>{children}</div>;
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="m-0 rounded-xl border border-dashed border-line-dark p-4 text-body text-ink-soft">{children}</p>;
}

interface ClaimButtonListProps {
  claims: readonly ClaimResponse[];
  selectedClaimId: string | null;
  onSelectClaim: (claimId: string) => void;
  numbered?: boolean;
  label: string;
}

/** Every claim is a button: statement + status + page, click opens the drawer. */
export function ClaimButtonList({ claims, selectedClaimId, onSelectClaim, numbered = false, label }: ClaimButtonListProps) {
  return (
    <ol aria-label={label} className="m-0 flex list-none flex-col gap-2 p-0">
      {claims.map((claim, index) => {
        const page = firstPage(claim);
        return (
          <li key={claim.id}>
            <button
              type="button"
              onClick={() => onSelectClaim(claim.id)}
              aria-pressed={claim.id === selectedClaimId}
              className={cn(
                "flex w-full items-start gap-3 rounded-lg border bg-surface p-3 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-paper-accent",
                claim.id === selectedClaimId ? "border-paper-accent" : "border-line",
              )}
            >
              {numbered && (
                <span aria-hidden="true" className="font-display text-h4 leading-6 text-paper-accent">
                  {index + 1}
                </span>
              )}
              <span className="flex-1 text-body text-ink">{claim.statement}</span>
              <span className="flex shrink-0 flex-col items-end gap-1">
                <VerificationBadge status={claim.verification_status} size="inline" />
                {page !== null && <span className="text-caption text-ink-soft">p. {page}</span>}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/** Numbers carry the meaning; the fill colour is a supplemental band only. */
export function Meter({ value, max, label }: { value: number; max: number; label: string }) {
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const band = ratio >= 0.8 ? "bg-verified" : ratio >= 0.5 ? "bg-partial" : "bg-mismatch";
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      aria-valuetext={`${value} of ${max}`}
      className="h-2 rounded-full bg-secondary"
    >
      <div className={cn("h-full rounded-full", band)} style={{ width: `${ratio * 100}%` }} />
    </div>
  );
}
