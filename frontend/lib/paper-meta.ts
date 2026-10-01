import type { PaperResponse } from "@/lib/paper-types";

export function formatCreatedDate(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** "Vaswani, Shazeer +6" style summary; never invents authors. */
export function summarizeAuthors(authors: readonly string[], max = 3): string {
  if (authors.length === 0) return "Unknown authors";
  const shown = authors.slice(0, max).join(", ");
  return authors.length > max ? `${shown} +${authors.length - max}` : shown;
}

/** Accent-insensitive, case-insensitive match on title and authors. */
export function matchesQuery(paper: PaperResponse, query: string): boolean {
  const needle = fold(query.trim());
  if (!needle) return true;
  return fold(`${paper.title} ${paper.authors.join(" ")}`).includes(needle);
}

function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}
