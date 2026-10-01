import type { ComparisonItem } from "@/lib/story-api";
import { cn } from "@/lib/utils";

const MIN_BAR_PERCENT = 4;

/** Bars scale to the largest value; a minimum width keeps tiny or
 * non-positive values visible. The number is always printed as text. */
export function barPercent(value: number, max: number): number {
  if (!(max > 0) || !(value > 0)) return MIN_BAR_PERCENT;
  return Math.max(MIN_BAR_PERCENT, (value / max) * 100);
}

export function ComparisonVisual({ items }: { items: ComparisonItem[] }) {
  const max = Math.max(0, ...items.map((item) => item.value));
  return (
    <ul className="m-0 flex list-none flex-col gap-3 p-0">
      {items.map((item, index) => (
        <li key={`${item.label}-${index}`} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-3 text-ui-label">
            <span className={cn(item.highlight ? "font-semibold text-ink" : "text-ink-soft")}>
              {item.label}
              {item.highlight && (
                <span className="ml-1.5 rounded-sm border border-paper-accent px-1 text-caption text-paper-accent">
                  Highlighted
                </span>
              )}
            </span>
            <span className={cn("tabular-nums", item.highlight ? "font-semibold text-ink" : "text-ink-soft")}>
              {item.display_value}
            </span>
          </div>
          <div className="h-3 rounded-full bg-secondary" aria-hidden="true">
            <div
              data-bar=""
              className={cn(
                "h-full rounded-full motion-safe:transition-[width] motion-safe:duration-500",
                item.highlight ? "bg-paper-accent" : "bg-line-dark",
              )}
              style={{ width: `${barPercent(item.value, max)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
