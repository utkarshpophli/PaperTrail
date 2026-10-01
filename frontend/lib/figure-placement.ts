import type { Figure } from "./story-api";

export interface FigurePlacement {
  bySection: Map<string, Figure[]>;
  unplaced: Figure[];
}

export interface PlaceableSection {
  id: string;
  claim_ids: readonly string[];
  /** The section's own prose; a section that names "Figure 2" is the best home for Figure 2. */
  text?: string;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function mentions(text: string | undefined, label: string | null): boolean {
  if (!text || !label) return false;
  // "Figure 2" must not match "Figure 21".
  return new RegExp(`\\b${escapeRegExp(label)}(?!\\d)`, "i").test(text);
}

/** Deterministic, no model: a figure goes to the FIRST section (in the given
 * order) whose text names it ("Figure 2", "Table 3"), else the first whose
 * claim_ids intersect the figure's own; each figure at most once. Everything
 * else is returned as `unplaced` (shown in Lab > Overview). */
export function placeFigures(sections: readonly PlaceableSection[], figures: readonly Figure[]): FigurePlacement {
  const bySection = new Map<string, Figure[]>();
  const unplaced: Figure[] = [];
  const claimSets = sections.map((s) => ({ id: s.id, text: s.text, ids: new Set(s.claim_ids) }));

  for (const figure of figures) {
    const home =
      claimSets.find((s) => mentions(s.text, figure.label)) ??
      claimSets.find((s) => figure.claim_ids.some((id) => s.ids.has(id)));
    if (!home) {
      unplaced.push(figure);
      continue;
    }
    bySection.set(home.id, [...(bySection.get(home.id) ?? []), figure]);
  }
  return { bySection, unplaced };
}
