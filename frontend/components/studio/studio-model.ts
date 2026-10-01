import type { CitingSection } from "@/lib/evidence-health";
import type { ClaimResponse, EvidenceResponse, GeneratedSectionResponse, LearningResponse } from "@/lib/evidence-api";
import type { StorySpec } from "@/lib/story-api";
import type { Loadable } from "./use-loadable";

// "code" (repository links, implementation plan, coding-agent handoff) is held
// back for a later release; code-mode.tsx is kept but not mounted.
export type StudioMode = "lab" | "story" | "preview";

export const STUDIO_MODES: readonly { id: StudioMode; label: string }[] = [
  { id: "lab", label: "Lab" },
  { id: "story", label: "Story" },
  { id: "preview", label: "Preview" },
];

export type StoryView =
  | { kind: "loading" }
  | { kind: "typed"; spec: StorySpec }
  | { kind: "plain"; sections: GeneratedSectionResponse[] }
  | { kind: "none" }
  | { kind: "error"; message: string };

/** Typed story-spec wins; the old plain story is a text-only fallback when
 * no spec exists (older analyses); otherwise empty. */
export function resolveStory(spec: Loadable<StorySpec>, plain: Loadable<GeneratedSectionResponse[]>): StoryView {
  if (spec.status === "ready" && spec.data.sections.length > 0) return { kind: "typed", spec: spec.data };
  if (spec.status === "loading" || plain.status === "loading") return { kind: "loading" };
  if (plain.status === "ready" && plain.data.length > 0) {
    return { kind: "plain", sections: [...plain.data].sort((a, b) => a.order - b.order) };
  }
  if (spec.status === "error") return { kind: "error", message: spec.message };
  return { kind: "none" };
}

interface SectionSources {
  story: StoryView;
  report: GeneratedSectionResponse[];
  technical: GeneratedSectionResponse[];
  learning: LearningResponse | null;
}

/** Everything that cites claims, flattened for the evidence-health view. */
export function buildCitingSections({ story, report, technical, learning }: SectionSources): CitingSection[] {
  const fromGenerated = (rows: GeneratedSectionResponse[], source: CitingSection["source"]): CitingSection[] =>
    rows.map((r) => ({ id: `${source}-${r.id}`, title: r.title, source, claimIds: r.claim_ids }));

  const storySections: CitingSection[] =
    story.kind === "typed"
      ? story.spec.sections.map((s) => ({
          id: `story-${s.id}`,
          title: `${s.index_label} ${s.title}`.trim(),
          source: "story",
          claimIds: s.claim_ids,
        }))
      : story.kind === "plain"
        ? fromGenerated(story.sections, "story")
        : [];

  const learningSections: CitingSection[] = learning
    ? [
        ...fromGenerated(learning.primer, "learning"),
        ...fromGenerated(learning.application_guide, "learning"),
        ...learning.quiz.map((q) => ({ id: `learning-quiz-${q.id}`, title: `Quiz: ${q.question}`, source: "learning" as const, claimIds: q.claim_ids })),
        ...learning.derivations.map((d) => ({
          id: `learning-derivation-${d.id}`,
          title: `Derivation: ${d.title}`,
          source: "learning" as const,
          claimIds: d.steps.flatMap((step) => step.claim_ids),
        })),
        ...learning.interactives.map((i) => ({ id: `learning-interactive-${i.id}`, title: `Interactive: ${i.title}`, source: "learning" as const, claimIds: i.claim_ids })),
      ]
    : [];

  return [...storySections, ...fromGenerated(report, "report"), ...fromGenerated(technical, "technical"), ...learningSections];
}

/** Immutably replaces one claim by id everywhere it appears -- methods/
 * findings/limitations/claims are all derived views over the same rows, so a
 * re-verify result has to be patched into all four lists. */
export function replaceClaim(evidence: EvidenceResponse, updated: ClaimResponse): EvidenceResponse {
  const swap = (claims: ClaimResponse[]): ClaimResponse[] => claims.map((c) => (c.id === updated.id ? updated : c));
  return {
    ...evidence,
    methods: swap(evidence.methods),
    findings: swap(evidence.findings),
    limitations: swap(evidence.limitations),
    claims: swap(evidence.claims),
  };
}
