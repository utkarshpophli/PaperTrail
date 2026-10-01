"use client";

import dynamic from "next/dynamic";
import { useMemo, useSyncExternalStore } from "react";
import type { ForceGraphProps, GraphData, NodeObject } from "react-force-graph-3d";
import type { NeuralMapEdge, NeuralMapNode } from "@/lib/discovery-api";
import {
  DEFAULT_RELATION_SWATCH,
  RELATION_COLORS,
  RELATION_LABELS,
  describeRelationProvenance,
  type LiteratureEdgeRelation,
} from "@/lib/literature-relations";

// react-force-graph-3d touches `window`/WebGL at module load — never let it
// evaluate during SSR.
const ForceGraph3D = dynamic<ForceGraphProps>(() => import("react-force-graph-3d"), { ssr: false });

const DEFAULT_NODE_SIZE = 4;

// Matches this project's existing md breakpoint (Tailwind md).
const WIDE_ENOUGH_FOR_3D_QUERY = "(min-width: 768px)";
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

// useSyncExternalStore (not a useEffect+setState pair) is the canonical way
// to subscribe to a browser API like matchMedia — it reads the live value on
// every render instead of triggering an extra setState-driven re-render.
function subscribeToMatchMedia(query: string) {
  return (onChange: () => void): (() => void) => {
    if (typeof window === "undefined" || !window.matchMedia) return () => {};
    const mql = window.matchMedia(query);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  };
}

function getMatchMediaSnapshot(query: string): boolean {
  return typeof window !== "undefined" && !!window.matchMedia && window.matchMedia(query).matches;
}

function useMatchMedia(query: string): boolean {
  return useSyncExternalStore(
    subscribeToMatchMedia(query),
    () => getMatchMediaSnapshot(query),
    () => false, // server snapshot: matches nothing during SSR
  );
}

interface ClusterGroup {
  color: string;
  nodes: NeuralMapNode[];
}

function groupByColor(nodes: readonly NeuralMapNode[]): ClusterGroup[] {
  const order: string[] = [];
  const groups = new Map<string, NeuralMapNode[]>();
  for (const node of nodes) {
    const existing = groups.get(node.color);
    if (existing) {
      existing.push(node);
    } else {
      groups.set(node.color, [node]);
      order.push(node.color);
    }
  }
  return order.map((color) => ({ color, nodes: groups.get(color) ?? [] }));
}

/** Relations present in `edges`, in first-seen order. */
function presentRelations(edges: readonly NeuralMapEdge[]): LiteratureEdgeRelation[] {
  return [...new Set(edges.map((edge) => edge.relation))];
}

/** A graph made only of `semantically_similar` edges (Discover, or a library
 * with no citation refresh yet) renders exactly as it did before Phase 7 — no
 * legend, no per-edge text. */
function hasDistinguishedRelations(edges: readonly NeuralMapEdge[]): boolean {
  return edges.some((edge) => edge.relation !== "semantically_similar");
}

/** Text-labeled legend for only the relations actually present. The swatch is
 * a redundant cue; the label carries the meaning. */
function RelationLegend({ relations }: { relations: LiteratureEdgeRelation[] }) {
  return (
    <ul aria-label="Edge relations in this graph" className="flex flex-wrap gap-x-4 gap-y-1">
      {relations.map((relation) => (
        <li key={relation} className="flex items-center gap-1.5 text-caption text-foreground">
          <span
            className="h-0.5 w-4 shrink-0 rounded-full"
            style={{ backgroundColor: RELATION_COLORS[relation] ?? DEFAULT_RELATION_SWATCH }}
            aria-hidden="true"
          />
          {RELATION_LABELS[relation]}
        </li>
      ))}
    </ul>
  );
}

interface NeuralMapListProps {
  nodes: NeuralMapNode[];
  edges: NeuralMapEdge[];
  onNodeClick?: (nodeId: string) => void;
}

/**
 * Simplified 2D list/cluster view — the required fallback per docs/UI_UX.md,
 * not an afterthought: real `<button>` elements so it's keyboard- and
 * screen-reader-operable, grouped by `color` (the backend's cluster proxy).
 */
function NeuralMapList({ nodes, edges, onNodeClick }: NeuralMapListProps) {
  const groups = useMemo(() => groupByColor(nodes), [nodes]);
  const showRelations = hasDistinguishedRelations(edges);
  const labelById = useMemo(() => new Map(nodes.map((node) => [node.id, node.label])), [nodes]);
  // Each edge is listed once, under its source node ("source RELATION target").
  const edgesBySource = useMemo(() => {
    const bySource = new Map<string, NeuralMapEdge[]>();
    for (const edge of edges) bySource.set(edge.source, [...(bySource.get(edge.source) ?? []), edge]);
    return bySource;
  }, [edges]);
  return (
    <div className="flex flex-col gap-4">
      {showRelations && <RelationLegend relations={presentRelations(edges)} />}
      {groups.map((group, index) => (
        <div key={group.color}>
          <div className="mb-1.5 flex items-center gap-2">
            <span
              className="size-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: group.color }}
              aria-hidden="true"
            />
            <span className="text-ui-label font-medium text-foreground">Cluster {index + 1}</span>
          </div>
          <ul className="flex flex-col gap-1">
            {group.nodes.map((node) => (
              <li key={node.id}>
                <button
                  type="button"
                  onClick={() => onNodeClick?.(node.id)}
                  className="w-full rounded-md px-2 py-1 text-left text-body text-foreground hover:bg-muted"
                >
                  {node.label}
                </button>
                {showRelations && (edgesBySource.get(node.id) ?? []).length > 0 && (
                  <ul className="ml-4 flex flex-col gap-0.5 pb-1">
                    {(edgesBySource.get(node.id) ?? []).map((edge) => (
                      <li key={`${edge.target}-${edge.relation}`} className="text-caption text-muted-foreground">
                        {RELATION_LABELS[edge.relation]} {labelById.get(edge.target) ?? edge.target} (
                        {describeRelationProvenance(edge.relation, edge.weight)})
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export interface NeuralMapProps {
  nodes: NeuralMapNode[];
  edges: NeuralMapEdge[];
  onNodeClick?: (nodeId: string) => void;
}

/**
 * Shared, generic 3D force graph — Phase 7 reuses this unmodified for the
 * library-wide literature graph with a different edge set, so nothing
 * Discover-specific belongs here.
 *
 * The 3D WebGL view is never the only way to reach this data: the list
 * fallback always renders in the DOM (visually hidden via `sr-only` when the
 * 3D view is shown) so keyboard/screen-reader users always have a path in,
 * regardless of whether `prefers-reduced-motion`/width detection guessed
 * right for a given assistive setup.
 */
export function NeuralMap({ nodes, edges, onNodeClick }: NeuralMapProps) {
  const prefersReducedMotion = useMatchMedia(REDUCED_MOTION_QUERY);
  const isWideEnough = useMatchMedia(WIDE_ENOUGH_FOR_3D_QUERY);
  const show3d = isWideEnough && !prefersReducedMotion;

  const graphData: GraphData = useMemo(
    () => ({
      nodes: nodes.map((node) => ({
        id: node.id,
        label: node.label,
        color: node.color,
        size: node.size ?? DEFAULT_NODE_SIZE,
      })),
      // `color` is the library's default linkColor field; leaving it unset for
      // semantically_similar keeps those links rendering as before Phase 7.
      links: edges.map((edge) => ({ source: edge.source, target: edge.target, color: RELATION_COLORS[edge.relation] })),
    }),
    [nodes, edges],
  );

  function handleNodeClick(node: NodeObject): void {
    if (typeof node.id === "string") onNodeClick?.(node.id);
  }

  if (nodes.length === 0) {
    return (
      <div className="flex min-h-[320px] items-center justify-center rounded-lg border border-border bg-card p-4 text-body text-muted-foreground">
        No papers to map yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {show3d && hasDistinguishedRelations(edges) && (
        // Visible legend for the canvas; the sr-only list below carries its own
        // copy for assistive tech, so this one is hidden from it.
        <div aria-hidden="true">
          <RelationLegend relations={presentRelations(edges)} />
        </div>
      )}
      {show3d && (
        <div
          className="h-[480px] w-full overflow-hidden rounded-lg border border-border bg-card"
          aria-hidden="true"
        >
          <ForceGraph3D
            graphData={graphData}
            nodeLabel="label"
            nodeColor="color"
            nodeVal="size"
            onNodeClick={handleNodeClick}
          />
        </div>
      )}
      <div className={show3d ? "sr-only" : undefined}>
        <NeuralMapList nodes={nodes} edges={edges} onNodeClick={onNodeClick} />
      </div>
    </div>
  );
}
