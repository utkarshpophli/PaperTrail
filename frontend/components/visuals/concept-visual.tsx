import type { LabelDetail } from "@/lib/story-api";

function ConceptItem({ item }: { item: LabelDetail }) {
  return (
    <li className="rounded-lg border border-line bg-surface-2 p-3">
      <span className="block text-body font-semibold text-ink">{item.label}</span>
      {item.detail && <span className="block text-ui-label text-ink-soft">{item.detail}</span>}
    </li>
  );
}

/** Centre node with satellites split left/right of it (stacked on narrow screens). */
export function ConceptVisual({ center, items }: { center: string; items: LabelDetail[] }) {
  const left = items.filter((_, i) => i % 2 === 0);
  const right = items.filter((_, i) => i % 2 === 1);
  return (
    <div className="grid grid-cols-1 items-center gap-3 sm:grid-cols-[1fr_auto_1fr]">
      <ul className="m-0 flex list-none flex-col gap-2 p-0 sm:order-1">
        {left.map((item, i) => (
          <ConceptItem key={`${item.label}-${i}`} item={item} />
        ))}
      </ul>
      <div className="order-first flex justify-center sm:order-2">
        <span className="rounded-full border-2 border-paper-accent bg-surface px-5 py-4 text-center font-display text-h4 font-medium text-ink">
          {center}
        </span>
      </div>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 sm:order-3">
        {right.map((item, i) => (
          <ConceptItem key={`${item.label}-${i}`} item={item} />
        ))}
      </ul>
    </div>
  );
}
