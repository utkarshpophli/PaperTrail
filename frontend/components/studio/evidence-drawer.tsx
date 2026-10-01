"use client";

import { useEffect, useRef, useState } from "react";
import { Link2, RefreshCw, X } from "lucide-react";
import { VerificationBadge } from "@/components/verification-badge";
import { reverifyClaim, type ClaimResponse } from "@/lib/evidence-api";
import { cn } from "@/lib/utils";
import { KIND_LABEL } from "./claim-labels";
import { errorMessage } from "./use-loadable";

export const EMPTY_DRAWER_TEXT = "Click a finding, or a source tag inside the story, to see where it comes from";

interface EvidenceDrawerProps {
  claim: ClaimResponse | null;
  paperId: string;
  /** docked: sticky right column on wide screens. overlay: right-side sheet
   * (Story/Preview). Both become a bottom sheet below 980px. */
  variant: "docked" | "overlay";
  onClose: () => void;
  /** Re-verify result -- patched into the shared evidence by the studio. */
  onClaimUpdated: (claim: ClaimResponse) => void;
}

function claimPermalink(claimId: string): string {
  return `${window.location.origin}${window.location.pathname}#claim-${claimId}`;
}

function DrawerBody({ claim, paperId, onClaimUpdated }: Pick<EvidenceDrawerProps, "paperId" | "onClaimUpdated"> & { claim: ClaimResponse }) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [reverifying, setReverifying] = useState(false);
  const [reverifyError, setReverifyError] = useState<string | null>(null);

  async function copyLink(): Promise<void> {
    try {
      await navigator.clipboard.writeText(claimPermalink(claim.id));
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  async function reverify(): Promise<void> {
    setReverifying(true);
    setReverifyError(null);
    try {
      onClaimUpdated(await reverifyClaim(paperId, claim.id));
    } catch (error: unknown) {
      setReverifyError(errorMessage(error));
    } finally {
      setReverifying(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <VerificationBadge status={claim.verification_status} />
        <span className="rounded-full border border-line-dark px-2 py-0.5 text-caption font-medium text-ink-soft">
          {KIND_LABEL[claim.kind]}
        </span>
      </div>
      <h3 className="m-0 font-display text-h4 font-medium tracking-tight text-ink">{claim.statement}</h3>

      {claim.source_refs.length === 0 && <p className="text-ui-label text-ink-soft">No source reference recorded for this claim.</p>}
      <ul className="m-0 flex list-none flex-col gap-3 p-0">
        {claim.source_refs.map((ref) => (
          <li key={ref.id} className="rounded-lg border border-line bg-surface-2 p-3">
            <p className="m-0 mb-1.5 text-caption font-semibold uppercase tracking-wide text-ink-soft">
              Page {ref.page}
              {ref.locator ? ` · ${ref.locator}` : ""}
            </p>
            <blockquote className="m-0 whitespace-pre-wrap border-l-2 border-paper-accent pl-3 font-mono text-mono text-ink">
              {ref.excerpt}
            </blockquote>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void copyLink()}
          className="inline-flex items-center gap-1.5 rounded-md border border-line-dark bg-surface px-2.5 py-1 text-ui-label text-ink hover:bg-muted focus-visible:outline-2 focus-visible:outline-paper-accent"
        >
          <Link2 className="size-3.5" aria-hidden="true" />
          Copy link
        </button>
        <button
          type="button"
          onClick={() => void reverify()}
          disabled={reverifying}
          className="inline-flex items-center gap-1.5 rounded-md border border-line-dark bg-surface px-2.5 py-1 text-ui-label text-ink hover:bg-muted focus-visible:outline-2 focus-visible:outline-paper-accent disabled:opacity-50"
        >
          <RefreshCw className="size-3.5" aria-hidden="true" />
          {reverifying ? "Re-verifying…" : "Re-verify"}
        </button>
        <span aria-live="polite" className="text-caption text-ink-soft">
          {copyState === "copied" && "Link copied"}
          {copyState === "failed" && "Could not copy the link"}
        </span>
      </div>
      {reverifyError && (
        <p role="alert" className="m-0 text-caption text-mismatch">
          {reverifyError}
        </p>
      )}
    </div>
  );
}

export function EvidenceDrawer({ claim, paperId, variant, onClose, onClaimUpdated }: EvidenceDrawerProps) {
  const ref = useRef<HTMLElement>(null);
  const claimId = claim?.id ?? null;

  useEffect(() => {
    if (!claimId) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [claimId, onClose]);

  // Overlay steals focus so keyboard users land in it, and hands it back to
  // the chip that opened it when the claim is deselected.
  useEffect(() => {
    if (!claimId || variant !== "overlay") return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    ref.current?.focus();
    return () => opener?.focus?.();
  }, [claimId, variant]);

  if (variant === "overlay" && !claim) return null;

  return (
    <aside
      ref={ref}
      tabIndex={-1}
      aria-label="Evidence"
      className={cn(
        "z-40 overflow-y-auto border border-line-dark bg-surface p-4 shadow-lg outline-none",
        "fixed inset-x-0 bottom-0 max-h-[70vh] rounded-t-xl",
        variant === "overlay" &&
          "min-[980px]:inset-x-auto min-[980px]:bottom-4 min-[980px]:right-4 min-[980px]:top-20 min-[980px]:max-h-none min-[980px]:w-[380px] min-[980px]:rounded-xl",
        variant === "docked" &&
          "min-[980px]:sticky min-[980px]:inset-auto min-[980px]:top-[4.5rem] min-[980px]:max-h-[calc(100vh-5.5rem)] min-[980px]:rounded-xl min-[980px]:shadow-none",
        variant === "docked" && !claim && "hidden min-[980px]:block",
      )}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="m-0 text-caption font-semibold uppercase tracking-[0.14em] text-paper-accent">Evidence</p>
        {claim && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close evidence"
            className="rounded-md p-1 text-ink-soft hover:bg-muted focus-visible:outline-2 focus-visible:outline-paper-accent"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        )}
      </div>
      {claim ? (
        <DrawerBody key={claim.id} claim={claim} paperId={paperId} onClaimUpdated={onClaimUpdated} />
      ) : (
        <p className="m-0 text-body text-ink-soft">{EMPTY_DRAWER_TEXT}</p>
      )}
    </aside>
  );
}
