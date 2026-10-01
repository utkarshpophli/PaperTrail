"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiRequestError } from "@/lib/api-types";
import { ClaimReferenceList } from "@/components/claim-reference-list";
import {
  getLearning,
  type ClaimResponse,
  type DerivationResponse,
  type DerivationStepResponse,
  type InteractiveResponse,
  type LearningResponse,
  type QuizQuestionResponse,
} from "@/lib/evidence-api";
import { evaluateFormula, isDefinedResult, parseFormula, type FormulaNode } from "@/lib/formula-grammar";
import { GeneratedSectionsPanel } from "./generated-sections-panel";

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

interface QuizQuestionRowProps {
  question: QuizQuestionResponse;
  claims: ClaimResponse[];
}

/** Answer/explanation/sources stay hidden until revealed -- showing them by
 * default defeats the point of a quiz. */
function QuizQuestionRow({ question, claims }: QuizQuestionRowProps) {
  const [revealed, setRevealed] = useState(false);

  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-background p-3">
      <p className="text-body font-medium text-foreground">{question.question}</p>
      {question.options && (
        <ul className="flex flex-col gap-1 text-body text-foreground">
          {question.options.map((option) => (
            <li key={option}>{option}</li>
          ))}
        </ul>
      )}
      <button
        type="button"
        onClick={() => setRevealed((value) => !value)}
        aria-expanded={revealed}
        className="self-start text-ui-label text-primary hover:underline"
      >
        {revealed ? "Hide answer" : "Reveal answer"}
      </button>
      {revealed && (
        <div className="flex flex-col gap-2 border-t border-border pt-2">
          <p className="text-body text-foreground">
            <span className="font-medium">Answer: </span>
            {question.correct_answer}
          </p>
          <p className="text-body text-muted-foreground">{question.explanation}</p>
          <ClaimReferenceList claimIds={question.claim_ids} claims={claims} />
        </div>
      )}
    </li>
  );
}

interface QuizListProps {
  questions: QuizQuestionResponse[];
  claims: ClaimResponse[];
}

export function QuizList({ questions, claims }: QuizListProps) {
  if (questions.length === 0) return null;
  const ordered = [...questions].sort((a, b) => a.order - b.order);
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h3 className="text-h4 font-display font-semibold text-foreground">Quiz</h3>
      <ol className="flex flex-col gap-3">
        {ordered.map((question) => (
          <QuizQuestionRow key={question.id} question={question} claims={claims} />
        ))}
      </ol>
    </div>
  );
}

interface DerivationStepRowProps {
  step: DerivationStepResponse;
  claims: ClaimResponse[];
}

/** `formula` is inert display text -- rendered in a mono block, never
 * evaluated or treated as executable/interactive content. */
function DerivationStepRow({ step, claims }: DerivationStepRowProps) {
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-background p-3">
      <p className="text-body text-foreground">{step.explanation}</p>
      <p className="whitespace-pre-wrap rounded-md bg-muted px-2 py-1 font-mono text-mono text-foreground">
        {step.formula}
      </p>
      <ClaimReferenceList claimIds={step.claim_ids} claims={claims} />
    </li>
  );
}

interface DerivationListProps {
  derivations: DerivationResponse[];
  claims: ClaimResponse[];
}

export function DerivationList({ derivations, claims }: DerivationListProps) {
  if (derivations.length === 0) return null;
  const ordered = [...derivations].sort((a, b) => a.order - b.order);
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h3 className="text-h4 font-display font-semibold text-foreground">Derivations</h3>
      <ol className="flex flex-col gap-4">
        {ordered.map((derivation) => (
          <li key={derivation.id} className="flex flex-col gap-2 rounded-lg border border-border bg-background p-3">
            <h4 className="text-h4 font-display font-semibold text-foreground">{derivation.title}</h4>
            <ol className="flex flex-col gap-2">
              {derivation.steps.map((step, index) => (
                // ponytail: index key -- steps are a fixed, backend-ordered
                // list with no reordering/insertion in the UI
                <DerivationStepRow key={index} step={step} claims={claims} />
              ))}
            </ol>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Rounds to 4 decimal places and strips trailing zeros for display --
 * exact enough for a slider-driven estimate, without dumping float noise
 * (e.g. `0.30000000000000004`) into the UI. */
function formatOutput(value: number): string {
  return Number(value.toFixed(4)).toString();
}

interface InteractiveCardProps {
  interactive: InteractiveResponse;
  claims: ClaimResponse[];
}

/**
 * `interactive.formula` is re-parsed and validated here with the frontend's
 * own grammar (frontend/lib/formula-grammar.ts) -- the backend's validation
 * is not trusted as the only control. A formula this independent check
 * rejects is never evaluated, regardless of what the backend already
 * accepted. Recomputation on every slider change is a plain AST walk (no
 * `eval`/`new Function`), so it's instant and needs no debounce.
 */
function InteractiveCard({ interactive, claims }: InteractiveCardProps) {
  const paramNames = useMemo(() => interactive.parameters.map((param) => param.name), [interactive.parameters]);

  const ast = useMemo<FormulaNode | null>(() => {
    try {
      return parseFormula(interactive.formula, paramNames);
    } catch {
      return null;
    }
  }, [interactive.formula, paramNames]);

  const [paramValues, setParamValues] = useState<Record<string, number>>(() =>
    Object.fromEntries(interactive.parameters.map((param) => [param.name, param.default])),
  );

  const outputDisplay = (() => {
    if (ast === null) return "Formula unavailable";
    const result = evaluateFormula(ast, paramValues);
    return isDefinedResult(result) ? formatOutput(result) : "undefined";
  })();

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-border bg-background p-3">
      <div className="flex flex-col gap-1">
        <h4 className="text-h4 font-display font-semibold text-foreground">{interactive.title}</h4>
        <p className="text-body text-muted-foreground">{interactive.description}</p>
      </div>

      <div className="flex flex-col gap-3">
        {interactive.parameters.map((param) => (
          <div key={param.name} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between">
              <label htmlFor={`${interactive.id}-${param.name}`} className="text-ui-label text-foreground">
                {param.label}
              </label>
              {/* Value display for sighted users -- aria-hidden because the
                  range input's own value/min/max are already exposed to
                  assistive tech natively; this span mustn't become part of
                  the label's accessible name (it changes on every drag). */}
              <span aria-hidden="true" className="text-caption text-muted-foreground">
                {paramValues[param.name]}
                {param.unit ? ` ${param.unit}` : ""}
              </span>
            </div>
            <input
              id={`${interactive.id}-${param.name}`}
              type="range"
              min={param.min}
              max={param.max}
              step={param.step}
              value={paramValues[param.name]}
              onChange={(event) => {
                const next = Number(event.target.value);
                setParamValues((values) => ({ ...values, [param.name]: next }));
              }}
              className="w-full accent-primary"
            />
          </div>
        ))}
      </div>

      <p className="text-body font-medium text-foreground">
        {interactive.output_label}: <span className="font-mono text-mono">{outputDisplay}</span>
      </p>

      <ClaimReferenceList claimIds={interactive.claim_ids} claims={claims} />
    </li>
  );
}

interface InteractiveListProps {
  interactives: InteractiveResponse[];
  claims: ClaimResponse[];
}

export function InteractiveList({ interactives, claims }: InteractiveListProps) {
  if (interactives.length === 0) return null;
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h3 className="text-h4 font-display font-semibold text-foreground">Interactive</h3>
      <ol className="flex flex-col gap-4">
        {interactives.map((interactive) => (
          <InteractiveCard key={interactive.id} interactive={interactive} claims={claims} />
        ))}
      </ol>
    </div>
  );
}

type LearningState =
  | { status: "loading" }
  | { status: "not-generated" }
  | { status: "error"; message: string }
  | { status: "ready"; learning: LearningResponse };

interface LearningPanelProps {
  paperId: string;
  claims: ClaimResponse[];
  /** Bumped by the parent after a new analysis run completes, to refetch. */
  refreshKey: number;
}

export function LearningPanel({ paperId, claims, refreshKey }: LearningPanelProps) {
  const [state, setState] = useState<LearningState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    getLearning(paperId)
      .then((learning) => {
        if (!cancelled) setState({ status: "ready", learning });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiRequestError && error.code === "learning_not_found") {
          setState({ status: "not-generated" });
          return;
        }
        setState({ status: "error", message: errorMessage(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [paperId, refreshKey]);

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Learning Layer</h2>

      {state.status === "loading" && <p className="text-body text-muted-foreground">Loading…</p>}

      {state.status === "not-generated" && (
        <p className="text-body text-muted-foreground">
          Not generated yet. Select &ldquo;Story + Learning Layer&rdquo; in the Analyze panel above and run
          analysis.
        </p>
      )}

      {state.status === "error" && (
        <p role="alert" className="text-body text-mismatch">
          {state.message}
        </p>
      )}

      {state.status === "ready" && (
        <>
          {/* Data's already fetched above -- these two reuse
              GeneratedSectionsPanel's ordered-list rendering/claim-linking
              without triggering a second network fetch. */}
          <GeneratedSectionsPanel
            title="Primer"
            paperId={paperId}
            claims={claims}
            fetchSections={() => Promise.resolve(state.learning.primer)}
            notFoundCode="learning_not_found"
            refreshKey={refreshKey}
            headingLevel="h3"
          />
          <GeneratedSectionsPanel
            title="Application Guide"
            paperId={paperId}
            claims={claims}
            fetchSections={() => Promise.resolve(state.learning.application_guide)}
            notFoundCode="learning_not_found"
            refreshKey={refreshKey}
            headingLevel="h3"
          />
          <QuizList questions={state.learning.quiz} claims={claims} />
          <DerivationList derivations={state.learning.derivations} claims={claims} />
          <InteractiveList interactives={state.learning.interactives} claims={claims} />
        </>
      )}
    </div>
  );
}
