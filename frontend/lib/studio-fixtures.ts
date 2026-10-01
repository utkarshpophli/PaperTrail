/** Shared test fixtures for the studio (claims, evidence, story spec). */

import type { ClaimResponse, EvidenceResponse, VerificationStatus, ClaimKind } from "./evidence-api";
import type { Figure, StorySpec } from "./story-api";

export function makeClaim(
  id: string,
  overrides: Partial<{ statement: string; kind: ClaimKind; status: VerificationStatus; pages: number[]; excerpt: string }> = {},
): ClaimResponse {
  const pages = overrides.pages ?? [1];
  return {
    id,
    statement: overrides.statement ?? `Statement of ${id}`,
    kind: overrides.kind ?? "reported-result",
    verification_status: overrides.status ?? "verified",
    source_refs: pages.map((page, i) => ({
      id: `${id}-ref-${i}`,
      page,
      excerpt: overrides.excerpt ?? `Quote for ${id} on page ${page}`,
      locator: null,
    })),
    created_at: "2026-01-01T00:00:00Z",
  };
}

export function makeEvidence(claims: ClaimResponse[]): EvidenceResponse {
  return {
    paper_id: "paper-1",
    thesis: "Attention is enough.",
    plain_summary: "A model built on attention only.",
    research_question: "Can we drop recurrence?",
    methods: claims.filter((c) => c.kind === "method"),
    findings: claims.filter((c) => c.kind === "reported-result"),
    limitations: claims.filter((c) => c.kind === "limitation"),
    claims,
    metrics: [
      {
        id: "m1",
        label: "BLEU",
        value: "28.4",
        display_value: "28.4",
        unit: "BLEU",
        context: "WMT14 En-De",
        source_page: 8,
        source_excerpt: "28.4 BLEU",
      },
    ],
    glossary: [
      { id: "g1", term: "Self-attention", definition: "Relates positions of one sequence.", source_page: 2, source_excerpt: null },
    ],
  };
}

export function makeFigure(id: string, claimIds: string[], overrides: Partial<Figure> = {}): Figure {
  return {
    id,
    filename: `${id}.png`,
    page: 3,
    label: "Figure 1",
    caption: `Caption of ${id}`,
    why_it_matters: null,
    claim_ids: claimIds,
    ...overrides,
  };
}

export const STORY_SPEC_FIXTURE: StorySpec = {
  meta: {
    title: "Attention, unrolled",
    dek: "A story about dropping recurrence.",
    reading_time: "6 min",
    closing: { title: "What to take away", body: "Attention scales." },
  },
  sections: [
    {
      id: "s1",
      index_label: "01",
      kicker: "The problem",
      title: "Recurrence is slow",
      body: "First paragraph.\n\nSecond paragraph.",
      claim_ids: ["c1", "c2"],
      visual: { type: "metric", eyebrow: "Headline", caption: "Numbers from the paper.", items: [{ label: "BLEU", value: "28.4", note: "En-De" }] },
    },
    {
      id: "s2",
      index_label: "02",
      kicker: "The idea",
      title: "Attention only",
      body: "Body two.",
      claim_ids: ["c3"],
      visual: { type: "quote", eyebrow: "In their words", caption: "Verbatim.", quote: "We propose a new architecture", attribution: "Abstract, p. 1" },
    },
  ],
};
