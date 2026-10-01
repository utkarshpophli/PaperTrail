/**
 * Story spec + figure list. The story-spec payload comes from an LLM-backed
 * pipeline, so it is parsed defensively (unknown + narrowing): a malformed
 * item is dropped, a malformed section is dropped, an unknown visual type
 * degrades to a caption-only fallback -- never a crash.
 */

import { apiFetch } from "./api-client";

export type VisualTone = "paper" | "accent" | "ink";
export type CellTone = "low" | "medium" | "high" | "neutral";
export type NodeGroup = "input" | "core" | "output" | "evidence";

export interface LabelDetail {
  label: string;
  detail: string;
}
export interface MetricItem {
  label: string;
  value: string;
  note: string;
}
export interface ComparisonItem {
  label: string;
  value: number;
  display_value: string;
  highlight: boolean;
}
export interface ToneItem extends LabelDetail {
  tone: VisualTone;
}
export interface ArchitectureNode {
  id: string;
  label: string;
  detail: string;
  group: NodeGroup;
}
export interface ArchitectureEdge {
  source: string;
  target: string;
  label: string;
}
export interface EquationTerm {
  symbol: string;
  label: string;
  detail: string;
}
export interface MatrixCell {
  label: string;
  tone: CellTone;
}
export interface MatrixRow {
  label: string;
  cells: MatrixCell[];
}
export interface InfographicItem extends LabelDetail {
  badge: string;
}

interface VisualBase {
  eyebrow: string;
  caption: string;
}

export type Visual =
  | (VisualBase & { type: "metric"; items: MetricItem[] })
  | (VisualBase & { type: "flow"; items: LabelDetail[] })
  | (VisualBase & { type: "comparison"; items: ComparisonItem[] })
  | (VisualBase & { type: "concept"; center: string; items: LabelDetail[] })
  | (VisualBase & { type: "layers"; items: ToneItem[] })
  | (VisualBase & { type: "quote"; quote: string; attribution: string })
  | (VisualBase & { type: "architecture"; nodes: ArchitectureNode[]; edges: ArchitectureEdge[] })
  | (VisualBase & { type: "equation"; formula: string; terms: EquationTerm[]; steps: string[] })
  | (VisualBase & { type: "timeline"; items: ToneItem[] })
  | (VisualBase & { type: "matrix"; columns: string[]; rows: MatrixRow[] })
  | (VisualBase & { type: "infographic"; items: InfographicItem[] })
  /** Unknown/unparseable type from the backend: caption only. */
  | (VisualBase & { type: "unsupported"; rawType: string });

export interface StorySection {
  id: string;
  index_label: string;
  kicker: string;
  title: string;
  body: string;
  claim_ids: string[];
  visual: Visual | null;
}

export interface StoryMeta {
  title: string;
  dek: string;
  reading_time: string;
  closing: { title: string; body: string } | null;
}

export interface StorySpec {
  meta: StoryMeta;
  sections: StorySection[];
}

export interface Figure {
  id: string;
  filename: string;
  page: number;
  label: string | null;
  caption: string | null;
  why_it_matters: string | null;
  claim_ids: string[];
}

type Rec = Record<string, unknown>;

function isRec(value: unknown): value is Rec {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Non-string scalars are stringified (a model may emit 42 for "value");
 * everything else falls back to `fallback`. */
function str(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return fallback;
}

function strList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

function list<T>(value: unknown, parse: (record: Rec) => T | null): T[] {
  if (!Array.isArray(value)) return [];
  const out: T[] = [];
  for (const entry of value) {
    if (!isRec(entry)) continue;
    const parsed = parse(entry);
    if (parsed) out.push(parsed);
  }
  return out;
}

const TONES = ["paper", "accent", "ink"] as const;
const CELL_TONES = ["low", "medium", "high", "neutral"] as const;
const GROUPS = ["input", "core", "output", "evidence"] as const;

function labelDetail(r: Rec): LabelDetail | null {
  const label = str(r.label);
  return label ? { label, detail: str(r.detail) } : null;
}

function toneItem(r: Rec): ToneItem | null {
  const base = labelDetail(r);
  return base ? { ...base, tone: oneOf(r.tone, TONES, "paper") } : null;
}

function parseVisual(value: unknown): Visual | null {
  if (!isRec(value)) return null;
  const base = { eyebrow: str(value.eyebrow), caption: str(value.caption) };
  const type = str(value.type);
  switch (type) {
    case "metric":
      return {
        ...base,
        type,
        items: list(value.items, (r) => {
          const label = str(r.label);
          return label ? { label, value: str(r.value), note: str(r.note) } : null;
        }),
      };
    case "flow":
      return { ...base, type, items: list(value.items, labelDetail) };
    case "comparison":
      return {
        ...base,
        type,
        items: list(value.items, (r) => {
          const label = str(r.label);
          if (!label || typeof r.value !== "number" || !Number.isFinite(r.value)) return null;
          return {
            label,
            value: r.value,
            display_value: str(r.display_value, String(r.value)),
            highlight: r.highlight === true,
          };
        }),
      };
    case "concept":
      return { ...base, type, center: str(value.center), items: list(value.items, labelDetail) };
    case "layers":
      return { ...base, type, items: list(value.items, toneItem) };
    case "quote":
      return { ...base, type, quote: str(value.quote), attribution: str(value.attribution) };
    case "architecture":
      return {
        ...base,
        type,
        nodes: list(value.nodes, (r) => {
          const id = str(r.id);
          const label = str(r.label);
          return id && label ? { id, label, detail: str(r.detail), group: oneOf(r.group, GROUPS, "core") } : null;
        }),
        edges: list(value.edges, (r) => {
          const source = str(r.source);
          const target = str(r.target);
          return source && target ? { source, target, label: str(r.label) } : null;
        }),
      };
    case "equation":
      return {
        ...base,
        type,
        formula: str(value.formula),
        terms: list(value.terms, (r) => {
          const symbol = str(r.symbol);
          return symbol ? { symbol, label: str(r.label), detail: str(r.detail) } : null;
        }),
        steps: strList(value.steps),
      };
    case "timeline":
      return { ...base, type, items: list(value.items, toneItem) };
    case "matrix":
      return {
        ...base,
        type,
        columns: strList(value.columns),
        rows: list(value.rows, (r) => {
          const label = str(r.label);
          if (!label) return null;
          const cells = list(r.cells, (c) => ({ label: str(c.label), tone: oneOf(c.tone, CELL_TONES, "neutral") }));
          return { label, cells };
        }),
      };
    case "infographic":
      return {
        ...base,
        type,
        items: list(value.items, (r) => {
          const base2 = labelDetail(r);
          return base2 ? { ...base2, badge: str(r.badge) } : null;
        }),
      };
    default:
      return { ...base, type: "unsupported", rawType: type };
  }
}

function parseSection(r: Rec): StorySection | null {
  const id = str(r.id);
  const title = str(r.title);
  if (!id || !title) return null;
  return {
    id,
    index_label: str(r.index_label),
    kicker: str(r.kicker),
    title,
    body: str(r.body),
    claim_ids: strList(r.claim_ids),
    visual: parseVisual(r.visual),
  };
}

export function parseStorySpec(data: unknown): StorySpec | null {
  if (!isRec(data) || !isRec(data.meta)) return null;
  const meta = data.meta;
  const closing = isRec(meta.closing) ? { title: str(meta.closing.title), body: str(meta.closing.body) } : null;
  return {
    meta: {
      title: str(meta.title),
      dek: str(meta.dek),
      reading_time: str(meta.reading_time),
      closing: closing && (closing.title || closing.body) ? closing : null,
    },
    sections: list(data.sections, parseSection),
  };
}

export function parseFigures(data: unknown): Figure[] {
  return list(data, (r) => {
    const filename = str(r.filename);
    const page = typeof r.page === "number" ? r.page : Number.NaN;
    if (!filename || !Number.isFinite(page)) return null;
    const nullable = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
    return {
      id: str(r.id, filename),
      filename,
      page,
      label: nullable(r.label),
      caption: nullable(r.caption),
      why_it_matters: nullable(r.why_it_matters),
      claim_ids: strList(r.claim_ids),
    };
  });
}

/** Rejects with ApiRequestError code `story_not_found` when none exists yet. */
export async function getStorySpec(paperId: string): Promise<StorySpec> {
  const spec = parseStorySpec(await apiFetch<unknown>(`/papers/${paperId}/story-spec`));
  if (!spec) throw new Error("The story data returned by the server is malformed.");
  return spec;
}

export async function getFigures(paperId: string): Promise<Figure[]> {
  return parseFigures(await apiFetch<unknown>(`/papers/${paperId}/figures`));
}
