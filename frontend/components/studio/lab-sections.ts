export type LabSectionId =
  | "overview"
  | "primer"
  | "learn"
  | "report"
  | "technical"
  | "claims"
  | "health"
  | "method"
  | "metrics"
  | "limitations"
  | "glossary"
  | "citations"
  | "ask"
  | "pages"
  | "reanalyze";

interface LabSectionDef {
  id: LabSectionId;
  label: string;
  /** Needs an analysis to exist; otherwise the not-analyzed empty state shows. */
  needsEvidence: boolean;
}

export const LAB_SECTIONS: readonly LabSectionDef[] = [
  { id: "overview", label: "Overview", needsEvidence: true },
  { id: "primer", label: "Primer", needsEvidence: true },
  { id: "learn", label: "Learn & Try", needsEvidence: true },
  { id: "report", label: "Deep report", needsEvidence: true },
  { id: "technical", label: "Technical", needsEvidence: true },
  { id: "claims", label: "Claims", needsEvidence: true },
  { id: "health", label: "Evidence health", needsEvidence: true },
  { id: "method", label: "Method", needsEvidence: true },
  { id: "metrics", label: "Metrics", needsEvidence: true },
  { id: "limitations", label: "Limitations", needsEvidence: true },
  { id: "glossary", label: "Glossary", needsEvidence: true },
  { id: "citations", label: "Citations", needsEvidence: false },
  { id: "ask", label: "Ask", needsEvidence: true },
  { id: "pages", label: "Pages", needsEvidence: false },
  { id: "reanalyze", label: "Re-analyze", needsEvidence: false },
];
