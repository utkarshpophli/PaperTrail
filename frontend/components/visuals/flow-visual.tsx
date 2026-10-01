import type { LabelDetail } from "@/lib/story-api";

export function FlowVisual({ items }: { items: LabelDetail[] }) {
  return (
    <ol className="m-0 flex list-none flex-col p-0">
      {items.map((item, index) => (
        <li key={`${item.label}-${index}`} className="relative flex gap-3 pb-4 last:pb-0">
          {index < items.length - 1 && (
            <span aria-hidden="true" className="absolute left-4 top-8 h-[calc(100%-2rem)] w-px bg-line-dark" />
          )}
          <span
            aria-hidden="true"
            className="z-10 flex size-8 shrink-0 items-center justify-center rounded-full border border-paper-accent bg-surface font-display text-body font-medium text-paper-accent"
          >
            {index + 1}
          </span>
          <div className="flex flex-col gap-0.5 pt-1">
            <span className="text-body font-semibold text-ink">
              <span className="sr-only">Step {index + 1}: </span>
              {item.label}
            </span>
            {item.detail && <span className="text-ui-label text-ink-soft">{item.detail}</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}
