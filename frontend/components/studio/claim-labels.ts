import type { ClaimKind } from "@/lib/evidence-api";

export const KIND_LABEL: Record<ClaimKind, string> = {
  "reported-result": "Reported result",
  "author-interpretation": "Author interpretation",
  method: "Method",
  background: "Background",
  limitation: "Limitation",
};

export function firstPage(claim: { source_refs: { page: number }[] }): number | null {
  return claim.source_refs[0]?.page ?? null;
}
