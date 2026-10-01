/**
 * Mirrors backend/app/graph/schemas.py::LiteratureEdgeRelation (the full
 * 12-value LiteratureEdge enum from docs/DATA_MODEL.md) plus the display
 * metadata shared by the Neural Map and the citations panel, so a relation
 * is labeled identically everywhere.
 */

export type LiteratureEdgeRelation =
  | "cites"
  | "extends"
  | "improves"
  | "reproduces"
  | "challenges"
  | "uses"
  | "inspired_by"
  | "benchmark"
  | "dataset"
  | "architecture"
  | "follow_up"
  | "semantically_similar";

export const RELATION_LABELS: Record<LiteratureEdgeRelation, string> = {
  cites: "Cites",
  extends: "Extends",
  improves: "Improves",
  reproduces: "Reproduces",
  challenges: "Challenges",
  uses: "Uses",
  inspired_by: "Inspired by",
  benchmark: "Benchmark",
  dataset: "Dataset",
  architecture: "Architecture",
  follow_up: "Follow-up",
  semantically_similar: "Semantically similar",
};

/** Swatch/link colors are a redundant cue only — every place that shows one
 * also shows RELATION_LABELS text. `semantically_similar` has no entry so it
 * keeps the 3D library's default link color, exactly as before Phase 7. */
export const RELATION_COLORS: Partial<Record<LiteratureEdgeRelation, string>> = {
  cites: "#64748b",
  extends: "#2563eb",
  improves: "#059669",
  reproduces: "#7c3aed",
  challenges: "#dc2626",
  uses: "#d97706",
  inspired_by: "#db2777",
  benchmark: "#0891b2",
  dataset: "#65a30d",
  architecture: "#9333ea",
  follow_up: "#ea580c",
};

/** Neutral swatch for the legend entry of the un-colored similarity edges. */
export const DEFAULT_RELATION_SWATCH = "#9ca3af";

/** True for the classifier-refined relations (everything but the external
 * `cites` fact and the embedding-derived similarity edges). */
export function isAiClassifiedRelation(relation: LiteratureEdgeRelation): boolean {
  return relation !== "cites" && relation !== "semantically_similar";
}

/**
 * Provenance text pairing a relation with how much to trust it: a plain
 * `cites` is an external OpenAlex record; anything more specific is a model's
 * guess and is labeled as such with its own confidence (backend
 * ARCHITECTURE.md, Phase 7 slice 2 "Confidence semantics").
 */
export function describeRelationProvenance(relation: LiteratureEdgeRelation, confidence: number | null): string {
  if (relation === "cites") return "Citation record (OpenAlex)";
  if (relation === "semantically_similar") return "Semantic similarity";
  const percent = confidence === null ? "" : `, ${Math.round(confidence * 100)}% confidence`;
  return `AI-classified${percent}`;
}
