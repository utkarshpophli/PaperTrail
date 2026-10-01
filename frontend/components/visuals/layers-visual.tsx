import type { ToneItem, VisualTone } from "@/lib/story-api";
import { cn } from "@/lib/utils";

const TONE_CLASS: Record<VisualTone, string> = {
  paper: "border-line bg-surface-2 text-ink",
  accent: "border-paper-accent bg-paper-accent text-on-accent",
  ink: "border-ink bg-ink text-on-ink",
};

export function LayersVisual({ items }: { items: ToneItem[] }) {
  return (
    <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
      {items.map((item, index) => (
        <li key={`${item.label}-${index}`} className={cn("rounded-lg border px-4 py-3", TONE_CLASS[item.tone])}>
          <span className="text-caption font-medium uppercase tracking-wide opacity-80">Layer {items.length - index}</span>
          <span className="block text-body font-semibold">{item.label}</span>
          {item.detail && <span className="block text-ui-label opacity-90">{item.detail}</span>}
        </li>
      ))}
    </ol>
  );
}
