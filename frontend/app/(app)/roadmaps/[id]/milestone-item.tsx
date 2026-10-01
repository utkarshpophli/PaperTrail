"use client";

import { CircleCheck, CircleDashed, CircleX, Lock, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { VerificationBadge } from "@/components/verification-badge";
import { cn } from "@/lib/utils";
import type { Concept, Milestone, MilestoneStatus, MilestoneUpdateStatus, PrerequisiteEdge } from "@/lib/discovery-api";

const SETTABLE_STATUSES: MilestoneUpdateStatus[] = ["available", "completed", "skipped"];

interface StatusConfig {
  label: string;
  icon: LucideIcon;
  textClass: string;
}

// Text/icon status indicator, never color alone (ui-design.md).
const STATUS_CONFIG: Record<MilestoneStatus, StatusConfig> = {
  locked: { label: "Locked", icon: Lock, textClass: "text-muted-foreground" },
  available: { label: "Available", icon: CircleDashed, textClass: "text-foreground" },
  completed: { label: "Completed", icon: CircleCheck, textClass: "text-verified" },
  skipped: { label: "Skipped", icon: CircleX, textClass: "text-not-found" },
};

function arxivAbsUrl(arxivId: string): string {
  return `https://arxiv.org/abs/${arxivId}`;
}

function resolveConcepts(conceptIds: string[], concepts: Concept[]): Concept[] {
  return conceptIds
    .map((id) => concepts.find((concept) => concept.id === id))
    .filter((concept): concept is Concept => concept !== undefined);
}

function prerequisiteNames(conceptId: string, edges: PrerequisiteEdge[], concepts: Concept[]): string[] {
  return edges
    .filter((edge) => edge.concept_id === conceptId)
    .map((edge) => concepts.find((concept) => concept.id === edge.prerequisite_concept_id)?.name)
    .filter((name): name is string => typeof name === "string");
}

export interface MilestoneItemProps {
  milestone: Milestone;
  concepts: Concept[];
  edges: PrerequisiteEdge[];
  onStatusChange: (status: MilestoneUpdateStatus) => void;
}

/** One roadmap milestone: status control (disabled while system-locked),
 * a link into the paper's existing reader/Primer if ingested, a plain
 * out-link to arXiv otherwise (never a fabricated in-app reader link for an
 * un-ingested candidate — same precedent as Phase 5's landscape cards), and
 * its concepts resolved with their prerequisite relationships. */
export function MilestoneItem({ milestone, concepts, edges, onStatusChange }: MilestoneItemProps) {
  const config = STATUS_CONFIG[milestone.status];
  const Icon = config.icon;
  const isLocked = milestone.status === "locked";
  const resolvedConcepts = resolveConcepts(milestone.concept_ids, concepts);

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-caption text-muted-foreground">Milestone {milestone.order}</p>
          <p className="text-h4 font-display font-semibold text-foreground">{milestone.title}</p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span
            role="status"
            data-testid="milestone-status"
            className={cn("inline-flex items-center gap-1 text-ui-label font-medium", config.textClass)}
          >
            <Icon className="size-3.5" aria-hidden="true" />
            {config.label}
          </span>
          <label className="sr-only" htmlFor={`milestone-status-${milestone.id}`}>
            Update milestone status
          </label>
          <select
            id={`milestone-status-${milestone.id}`}
            value={isLocked ? "" : milestone.status}
            disabled={isLocked}
            onChange={(event) => onStatusChange(event.target.value as MilestoneUpdateStatus)}
            className="rounded-md border border-input bg-background px-2 py-1 text-caption text-foreground disabled:opacity-50"
          >
            {isLocked && (
              <option value="" disabled>
                Locked
              </option>
            )}
            {SETTABLE_STATUSES.map((status) => (
              <option key={status} value={status}>
                {STATUS_CONFIG[status].label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {milestone.paper_id ? (
        <Link href={`/papers/${milestone.paper_id}`} className="text-ui-label text-primary hover:underline">
          Open paper
        </Link>
      ) : milestone.arxiv_id ? (
        <a
          href={arxivAbsUrl(milestone.arxiv_id)}
          target="_blank"
          rel="noreferrer"
          className="text-ui-label text-primary hover:underline"
        >
          Open on arXiv (not yet ingested)
        </a>
      ) : null}

      {resolvedConcepts.length > 0 && (
        <ul className="flex flex-col gap-2 border-t border-border pt-2">
          {resolvedConcepts.map((concept) => {
            const prereqs = prerequisiteNames(concept.id, edges, concepts);
            return (
              <li key={concept.id} className="flex flex-col gap-0.5">
                <div className="flex items-center gap-1.5">
                  <p className="text-ui-label font-medium text-foreground">{concept.name}</p>
                  <VerificationBadge status={concept.verification_status} size="inline" />
                </div>
                <p className="text-body text-muted-foreground">{concept.description}</p>
                {prereqs.length > 0 && (
                  <p className="pl-3 text-caption text-muted-foreground">Requires: {prereqs.join(", ")}</p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}
