import type { ReactNode } from "react";
import type { Visual } from "@/lib/story-api";
import { ArchitectureVisual } from "./architecture-visual";
import { ComparisonVisual } from "./comparison-visual";
import { ConceptVisual } from "./concept-visual";
import { EquationVisual } from "./equation-visual";
import { FlowVisual } from "./flow-visual";
import { InfographicVisual } from "./infographic-visual";
import { LayersVisual } from "./layers-visual";
import { MatrixVisual } from "./matrix-visual";
import { MetricVisual } from "./metric-visual";
import { QuoteVisual } from "./quote-visual";
import { TimelineVisual } from "./timeline-visual";
import { VisualFrame } from "./visual-frame";

function body(visual: Visual): ReactNode {
  switch (visual.type) {
    case "metric":
      return <MetricVisual items={visual.items} />;
    case "flow":
      return <FlowVisual items={visual.items} />;
    case "comparison":
      return <ComparisonVisual items={visual.items} />;
    case "concept":
      return <ConceptVisual center={visual.center} items={visual.items} />;
    case "layers":
      return <LayersVisual items={visual.items} />;
    case "quote":
      return <QuoteVisual quote={visual.quote} attribution={visual.attribution} />;
    case "architecture":
      return <ArchitectureVisual nodes={visual.nodes} edges={visual.edges} />;
    case "equation":
      return <EquationVisual formula={visual.formula} terms={visual.terms} steps={visual.steps} />;
    case "timeline":
      return <TimelineVisual items={visual.items} />;
    case "matrix":
      return <MatrixVisual columns={visual.columns} rows={visual.rows} />;
    case "infographic":
      return <InfographicVisual items={visual.items} />;
    default:
      // "unsupported" or a type this build doesn't know: caption only.
      return null;
  }
}

interface VisualRendererProps {
  visual: Visual;
  /** Preview mode marks the visual belonging to the section in view. */
  active?: boolean;
}

export function VisualRenderer({ visual, active }: VisualRendererProps) {
  return (
    <VisualFrame eyebrow={visual.eyebrow} caption={visual.caption} active={active}>
      {body(visual)}
    </VisualFrame>
  );
}
