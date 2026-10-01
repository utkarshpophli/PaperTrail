import type { ReactNode } from "react";

interface VisualFrameProps {
  eyebrow: string;
  caption: string;
  active?: boolean;
  children?: ReactNode;
}

/** Shared chrome for every visual grammar: eyebrow above, caption below. */
export function VisualFrame({ eyebrow, caption, active, children }: VisualFrameProps) {
  return (
    <figure
      data-visual-frame=""
      data-active={active === undefined ? undefined : String(active)}
      className="m-0 flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 sm:p-5"
    >
      {eyebrow && (
        <p className="text-caption font-semibold uppercase tracking-[0.14em] text-paper-accent">{eyebrow}</p>
      )}
      {children}
      {caption && <figcaption className="text-ui-label text-ink-soft">{caption}</figcaption>}
    </figure>
  );
}
