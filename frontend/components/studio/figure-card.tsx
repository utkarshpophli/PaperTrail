"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import type { Figure } from "@/lib/story-api";
import { figureUrl } from "@/lib/papers-api";

function figureAlt(figure: Figure): string {
  return figure.caption ?? figure.label ?? `Figure on page ${figure.page}`;
}

/** Fixed-aspect frame so the page never shifts when the image arrives; the
 * image is letterboxed inside it rather than resized. */
function FigureImage({ src, alt, onClick }: { src: string; alt: string; onClick: () => void }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <p className="m-0 flex aspect-[4/3] items-center justify-center rounded-lg border border-dashed border-line-dark bg-surface-2 p-4 text-center text-ui-label text-ink-soft">
        The image could not be loaded. The caption below is still from the paper.
      </p>
    );
  }
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Expand figure: ${alt}`}
      className="block aspect-[4/3] w-full cursor-zoom-in overflow-hidden rounded-lg border border-line bg-surface-2 focus-visible:outline-2 focus-visible:outline-paper-accent"
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- API-served extracted figure, dimensions unknown up front */}
      <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} className="size-full object-contain" />
    </button>
  );
}

function Lightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    // capture: closes the lightbox before the evidence drawer's Esc handler sees it
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [onClose]);

  return (
    <div role="dialog" aria-modal="true" aria-label="Expanded figure" className="fixed inset-0 z-50 flex items-center justify-center bg-ink/80 p-4">
      <button
        type="button"
        onClick={onClose}
        aria-label="Close expanded figure"
        autoFocus
        className="absolute right-4 top-4 rounded-full bg-surface p-2 text-ink focus-visible:outline-2 focus-visible:outline-paper-accent"
      >
        <X className="size-5" aria-hidden="true" />
      </button>
      {/* eslint-disable-next-line @next/next/no-img-element -- see above */}
      <img src={src} alt={alt} className="max-h-full max-w-full rounded-lg bg-surface object-contain" />
    </div>
  );
}

interface FigureCardProps {
  paperId: string;
  figure: Figure;
}

export function FigureCard({ paperId, figure }: FigureCardProps) {
  const [expanded, setExpanded] = useState(false);
  const src = figureUrl(paperId, figure.filename);
  const alt = figureAlt(figure);
  // A caption usually already opens with its label ("Figure 2 | ..."); don't repeat it.
  const captionHasLabel = figure.label && figure.caption?.toLowerCase().startsWith(figure.label.toLowerCase());
  const heading =
    figure.label && figure.caption && !captionHasLabel ? `${figure.label}: ${figure.caption}` : (figure.caption ?? figure.label);

  return (
    <figure className="m-0 flex flex-col gap-2 rounded-xl border border-line bg-surface p-3">
      <FigureImage src={src} alt={alt} onClick={() => setExpanded(true)} />
      {figure.why_it_matters && <p className="m-0 text-ui-label font-medium text-ink">{figure.why_it_matters}</p>}
      <figcaption className="flex flex-col gap-0.5">
        {heading && <span className="text-ui-label text-ink">{heading}</span>}
        <span className="text-caption text-ink-soft">From the paper, p. {figure.page}</span>
      </figcaption>
      {expanded && <Lightbox src={src} alt={alt} onClose={() => setExpanded(false)} />}
    </figure>
  );
}

export function FigureGrid({ paperId, figures }: { paperId: string; figures: readonly Figure[] }) {
  if (figures.length === 0) return null;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {figures.map((figure) => (
        <FigureCard key={figure.id} paperId={paperId} figure={figure} />
      ))}
    </div>
  );
}
