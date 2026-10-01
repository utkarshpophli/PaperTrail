import type { EquationTerm } from "@/lib/story-api";

/** The formula is inert plain text this milestone -- no LaTeX rendering, never evaluated. */
export function EquationVisual({ formula, terms, steps }: { formula: string; terms: EquationTerm[]; steps: string[] }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto rounded-lg border border-line bg-surface-2 px-4 py-5 text-center font-display text-h3 text-ink">
        {formula}
      </div>
      {terms.length > 0 && (
        <dl className="m-0 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {terms.map((term, index) => (
            <div key={`${term.symbol}-${index}`} className="flex gap-3 rounded-lg border border-line p-3">
              <dt className="min-w-8 font-display text-h4 text-paper-accent">{term.symbol}</dt>
              <dd className="m-0 flex flex-col text-ui-label">
                <span className="font-semibold text-ink">{term.label}</span>
                {term.detail && <span className="text-ink-soft">{term.detail}</span>}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {steps.length > 0 && (
        <ol className="m-0 list-decimal pl-5 text-body text-ink marker:font-semibold marker:text-paper-accent">
          {steps.map((step, index) => (
            <li key={index} className="py-0.5">
              {step}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
