import { CircleCheck, CircleX, Clock, Loader2, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ParseStatus } from "@/lib/paper-types";

/**
 * Separate from VerificationBadge on purpose: parse_status (pending/parsing/
 * parsed/failed, set by the document parser) is a different concept from
 * verification_status (the quote-exactness verifier's four states) — see
 * app/models/paper.py::ParseStatus vs app/evidence/verifier.py.
 */
interface StatusConfig {
  label: string;
  icon: LucideIcon;
  textClass: string;
  bgClass: string;
  spin?: boolean;
}

const STATUS_CONFIG: Record<ParseStatus, StatusConfig> = {
  pending: { label: "Pending", icon: Clock, textClass: "text-not-found", bgClass: "bg-not-found-bg" },
  parsing: { label: "Parsing…", icon: Loader2, textClass: "text-partial", bgClass: "bg-partial-bg", spin: true },
  parsed: { label: "Parsed", icon: CircleCheck, textClass: "text-verified", bgClass: "bg-verified-bg" },
  failed: { label: "Failed", icon: CircleX, textClass: "text-mismatch", bgClass: "bg-mismatch-bg" },
};

export interface ParseStatusIndicatorProps {
  status: ParseStatus;
  /** parse_error from PaperResponse — shown for the failed state only. */
  errorMessage?: string | null;
  className?: string;
}

// docs/ui-design.md: status uses text/icon, never color alone.
export function ParseStatusIndicator({ status, errorMessage, className }: ParseStatusIndicatorProps) {
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;

  return (
    <span
      role="status"
      className={cn(
        "inline-flex h-6 items-center gap-1 rounded-full px-2 font-sans text-ui-label font-medium",
        config.textClass,
        config.bgClass,
        className,
      )}
    >
      <Icon className={cn("size-3.5", config.spin && "animate-spin motion-reduce:animate-none")} aria-hidden="true" />
      {config.label}
      {status === "failed" && errorMessage ? <span>: {errorMessage}</span> : null}
    </span>
  );
}
