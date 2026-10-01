import { CircleAlert, CircleCheck, CircleHelp, CircleX, Search, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { VerificationStatus } from "@/lib/evidence-api";

export type { VerificationStatus };

interface StatusConfig {
  label: string;
  icon: LucideIcon;
  textClass: string;
  bgClass: string;
}

// docs/ui-design.md: verification status uses text/icon, never color alone.
const STATUS_CONFIG: Record<VerificationStatus, StatusConfig> = {
  verified: {
    label: "Verified",
    icon: CircleCheck,
    textClass: "text-verified",
    bgClass: "bg-verified-bg",
  },
  "partially-matched": {
    label: "Partial match",
    icon: CircleAlert,
    textClass: "text-partial",
    bgClass: "bg-partial-bg",
  },
  mismatch: {
    label: "Mismatch",
    icon: CircleX,
    textClass: "text-mismatch",
    bgClass: "bg-mismatch-bg",
  },
  "not-found": {
    label: "Not found",
    icon: CircleHelp,
    textClass: "text-not-found",
    bgClass: "bg-not-found-bg",
  },
  // Verifier couldn't reach a conclusion (e.g. cited page has no parsed
  // text) — distinct from "not-found" (likely fabricated), reuses its
  // neutral color token since both are "we can't confirm this" states, but
  // stays distinguishable by label/icon (never color alone).
  "needs-review": {
    label: "Needs review",
    icon: Search,
    textClass: "text-not-found",
    bgClass: "bg-not-found-bg",
  },
};

export interface VerificationBadgeProps {
  status: VerificationStatus;
  /** standalone: 24px height / ui-label type. inline: 20px height / caption type. */
  size?: "standalone" | "inline";
  className?: string;
}

export function VerificationBadge({ status, size = "standalone", className }: VerificationBadgeProps) {
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;
  const isInline = size === "inline";

  return (
    <span
      role="status"
      className={cn(
        "inline-flex items-center gap-1 rounded-full font-sans font-medium",
        config.textClass,
        config.bgClass,
        isInline ? "h-5 px-1.5 text-caption" : "h-6 px-2 text-ui-label",
        className,
      )}
    >
      <Icon className={isInline ? "size-3" : "size-3.5"} aria-hidden="true" />
      {config.label}
    </span>
  );
}
