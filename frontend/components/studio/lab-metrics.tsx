"use client";

import type { ClaimResponse, MetricResponse } from "@/lib/evidence-api";
import { EmptyNote, LabSection } from "./lab-parts";

interface LabMetricsProps {
  metrics: readonly MetricResponse[];
  claims: readonly ClaimResponse[];
  onSelectClaim: (claimId: string) => void;
}

export function LabMetrics({ metrics, claims, onSelectClaim }: LabMetricsProps) {
  return (
    <LabSection title="Metrics" intro="Numbers reported by the paper. Click one to see the first claim on the same page.">
      {metrics.length === 0 ? (
        <EmptyNote>No metrics were extracted.</EmptyNote>
      ) : (
        <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
          {metrics.map((metric) => {
            const claim = claims.find((c) => c.source_refs.some((ref) => ref.page === metric.source_page));
            return (
              <li key={metric.id}>
                <button
                  type="button"
                  disabled={!claim}
                  title={claim ? undefined : `No claim cites page ${metric.source_page}`}
                  onClick={() => claim && onSelectClaim(claim.id)}
                  className="flex h-full w-full flex-col gap-1 rounded-xl border border-line bg-surface p-4 text-left enabled:hover:bg-muted focus-visible:outline-2 focus-visible:outline-paper-accent"
                >
                  <span className="text-caption font-semibold uppercase tracking-wide text-ink-soft">{metric.label}</span>
                  <span className="flex items-baseline gap-1.5">
                    <span className="font-display text-h1 font-medium leading-none tracking-tight text-paper-accent">{metric.display_value}</span>
                    {metric.unit && <span className="text-ui-label text-ink-soft">{metric.unit}</span>}
                  </span>
                  {metric.context && <span className="text-ui-label text-ink">{metric.context}</span>}
                  <span className="text-caption text-ink-soft">Page {metric.source_page}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </LabSection>
  );
}
