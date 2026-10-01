export function QuoteVisual({ quote, attribution }: { quote: string; attribution: string }) {
  return (
    <blockquote className="m-0 border-l-4 border-paper-accent pl-4">
      <p className="m-0 font-display text-h3 font-medium tracking-tight text-ink">&ldquo;{quote}&rdquo;</p>
      {attribution && <footer className="mt-2 text-ui-label text-ink-soft">&mdash; {attribution}</footer>}
    </blockquote>
  );
}
