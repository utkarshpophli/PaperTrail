import type { ToneItem, VisualTone } from "@/lib/story-api";
import { cn } from "@/lib/utils";

const DOT_CLASS: Record<VisualTone, string> = {
  paper: "border-line-dark bg-surface",
  accent: "border-paper-accent bg-paper-accent",
  ink: "border-ink bg-ink",
};

export function TimelineVisual({ items }: { items: ToneItem[] }) {
  return (
    <ol className="m-0 list-none border-l border-line-dark p-0 pl-5">
      {items.map((item, index) => (
        <li key={`${item.label}-${index}`} className="relative pb-4 last:pb-0">
          <span
            aria-hidden="true"
            className={cn("absolute -left-[1.62rem] top-1.5 size-3 rounded-full border-2", DOT_CLASS[item.tone])}
          />
          <span className="block text-body font-semibold text-ink">{item.label}</span>
          {item.detail && <span className="block text-ui-label text-ink-soft">{item.detail}</span>}
        </li>
      ))}
    </ol>
  );
}
