import type { MetricItem } from "@/lib/story-api";

export function MetricVisual({ items }: { items: MetricItem[] }) {
  return (
    <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
      {items.map((item, index) => (
        <li key={`${item.label}-${index}`} className="flex flex-col gap-1 rounded-lg border border-line bg-surface-2 p-4">
          <span className="text-caption font-medium uppercase tracking-wide text-ink-soft">{item.label}</span>
          <span className="font-display text-h1 font-medium leading-none tracking-tight text-paper-accent">{item.value}</span>
          {item.note && <span className="text-ui-label text-ink-soft">{item.note}</span>}
        </li>
      ))}
    </ul>
  );
}
