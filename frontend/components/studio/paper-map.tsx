"use client";

import { cn } from "@/lib/utils";

export interface PaperMapItem {
  id: string;
  label: string;
}

interface PaperMapProps {
  items: readonly PaperMapItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
}

/** Left "Paper map": a vertical list on wide screens, a horizontal strip
 * below 980px. */
export function PaperMap({ items, activeId, onSelect }: PaperMapProps) {
  return (
    <nav
      aria-label="Paper map"
      className={cn(
        "sticky top-[3.75rem] z-20 border-b border-line bg-background/95 backdrop-blur",
        "min-[980px]:top-[4.5rem] min-[980px]:z-auto min-[980px]:self-start min-[980px]:border-b-0 min-[980px]:bg-transparent min-[980px]:backdrop-blur-none",
      )}
    >
      <p className="m-0 hidden px-2 pb-2 text-caption font-semibold uppercase tracking-[0.14em] text-ink-soft min-[980px]:block">
        Paper map
      </p>
      <ul className="m-0 flex list-none gap-1 overflow-x-auto p-2 min-[980px]:flex-col min-[980px]:overflow-visible min-[980px]:p-0">
        {items.map((item) => {
          const active = item.id === activeId;
          return (
            <li key={item.id} className="shrink-0">
              <button
                type="button"
                onClick={() => onSelect(item.id)}
                aria-current={active ? "true" : undefined}
                className={cn(
                  "w-full whitespace-nowrap rounded-md px-2.5 py-1.5 text-left text-ui-label focus-visible:outline-2 focus-visible:outline-paper-accent min-[980px]:whitespace-normal",
                  active ? "bg-ink font-medium text-on-ink" : "text-ink-soft hover:bg-muted hover:text-ink",
                )}
              >
                {item.label}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
