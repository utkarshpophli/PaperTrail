import { useId } from "react";
import type { ArchitectureEdge, ArchitectureNode, NodeGroup } from "@/lib/story-api";
import { GROUP_LABEL, NODE_H, NODE_W, layoutArchitecture, type ArchitectureLayout } from "./architecture-layout";

const NODE_CLASS: Record<NodeGroup, { box: string; text: string }> = {
  input: { box: "fill-surface-2 stroke-line-dark", text: "fill-ink" },
  core: { box: "fill-paper-accent stroke-paper-accent", text: "fill-on-accent" },
  output: { box: "fill-ink stroke-ink", text: "fill-on-ink" },
  evidence: { box: "fill-verified-bg stroke-verified [stroke-dasharray:5_3]", text: "fill-ink" },
};

function safeLayout(nodes: ArchitectureNode[], edges: ArchitectureEdge[]): ArchitectureLayout | null {
  try {
    return layoutArchitecture(nodes, edges);
  } catch {
    return null;
  }
}

function Diagram({ layout, markerId }: { layout: ArchitectureLayout; markerId: string }) {
  return (
    <div className="overflow-x-auto">
      <svg
        aria-hidden="true"
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="h-auto w-full"
        style={{ minWidth: Math.min(layout.width, 520) }}
      >
        <defs>
          <marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="fill-ink-soft" />
          </marker>
        </defs>
        {layout.columns.map((column) => (
          <text key={column.group} x={column.x} y={18} className="fill-ink-soft text-[11px] font-semibold uppercase tracking-widest">
            {GROUP_LABEL[column.group]}
          </text>
        ))}
        {layout.edges.map(({ edge, path, labelX, labelY }, i) => (
          <g key={`${edge.source}-${edge.target}-${i}`}>
            <path d={path} fill="none" className="stroke-ink-soft" strokeWidth={1.5} markerEnd={`url(#${markerId})`} />
            {edge.label && (
              <text
                x={labelX}
                y={labelY - 4}
                textAnchor="middle"
                className="fill-ink-soft text-[10px]"
                stroke="var(--surface)"
                strokeWidth={4}
                paintOrder="stroke"
              >
                {edge.label}
              </text>
            )}
          </g>
        ))}
        {layout.nodes.map(({ node, x, y, lines }) => (
          <g key={node.id}>
            <rect x={x} y={y} width={NODE_W} height={NODE_H} rx={10} strokeWidth={1.5} className={NODE_CLASS[node.group].box} />
            <text textAnchor="middle" className={`${NODE_CLASS[node.group].text} text-[12px] font-semibold`}>
              {lines.map((line, i) => (
                <tspan key={i} x={x + NODE_W / 2} y={y + NODE_H / 2 + (i - (lines.length - 1) / 2) * 15 + 4}>
                  {line}
                </tspan>
              ))}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

interface ArchitectureVisualProps {
  nodes: ArchitectureNode[];
  edges: ArchitectureEdge[];
}

/** The diagram is a visual aid; the component list and connection list below
 * always carry the same information as text (and are the whole visual when
 * the layout can't be drawn). */
export function ArchitectureVisual({ nodes, edges }: ArchitectureVisualProps) {
  const markerId = `arrow-${useId().replace(/:/g, "")}`;
  const layout = safeLayout(nodes, edges);
  const labelOf = new Map(nodes.map((n) => [n.id, n.label]));
  const drawnEdges = edges.filter((e) => labelOf.has(e.source) && labelOf.has(e.target));

  return (
    <div className="flex flex-col gap-3">
      {layout && <Diagram layout={layout} markerId={markerId} />}
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-ui-label">
        {nodes.map((node) => (
          <li key={node.id} className="text-ink">
            <span className="font-semibold">{node.label}</span>{" "}
            <span className="rounded-sm border border-line-dark px-1 text-caption text-ink-soft">{GROUP_LABEL[node.group]}</span>
            {node.detail && <span className="text-ink-soft"> &mdash; {node.detail}</span>}
          </li>
        ))}
      </ul>
      {drawnEdges.length > 0 && (
        <ul aria-label="Connections" className="m-0 flex list-none flex-col gap-1 p-0 text-ui-label text-ink-soft">
          {drawnEdges.map((edge, i) => (
            <li key={`${edge.source}-${edge.target}-${i}`}>
              {labelOf.get(edge.source)} &rarr; {labelOf.get(edge.target)}
              {edge.label ? `: ${edge.label}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
