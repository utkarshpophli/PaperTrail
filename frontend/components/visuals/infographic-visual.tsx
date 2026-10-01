import type { InfographicItem } from "@/lib/story-api";

export function InfographicVisual({ items }: { items: InfographicItem[] }) {
  return (
    <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
      {items.map((item, index) => (
        <li key={`${item.label}-${index}`} className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface-2 p-4">
          {item.badge && (
            <span className="self-start rounded-full border border-paper-accent px-2 py-0.5 text-caption font-semibold text-paper-accent">
              {item.badge}
            </span>
          )}
          <span className="text-body font-semibold text-ink">{item.label}</span>
          {item.detail && <span className="text-ui-label text-ink-soft">{item.detail}</span>}
        </li>
      ))}
    </ul>
  );
}
