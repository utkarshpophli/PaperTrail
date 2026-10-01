import type { ArchitectureEdge, ArchitectureNode, NodeGroup } from "@/lib/story-api";

export const NODE_W = 168;
export const NODE_H = 60;
const COL_GAP = 72;
const ROW_GAP = 24;
const PAD = 16;
const HEADER_H = 24;
const MAX_NODES = 24;
const MAX_LINE_CHARS = 22;

/** Left to right: input -> core -> output, evidence off to the far side. */
const GROUP_ORDER: readonly NodeGroup[] = ["input", "core", "output", "evidence"];

export const GROUP_LABEL: Record<NodeGroup, string> = {
  input: "Input",
  core: "Core",
  output: "Output",
  evidence: "Evidence",
};

export interface PlacedNode {
  node: ArchitectureNode;
  x: number;
  y: number;
  lines: string[];
}
export interface PlacedEdge {
  edge: ArchitectureEdge;
  path: string;
  labelX: number;
  labelY: number;
}
export interface ArchitectureLayout {
  width: number;
  height: number;
  columns: { group: NodeGroup; x: number }[];
  nodes: PlacedNode[];
  edges: PlacedEdge[];
}

/** Greedy word wrap into at most `maxLines`, ellipsising overflow. */
export function wrapLabel(text: string, maxChars = MAX_LINE_CHARS, maxLines = 2): string[] {
  const lines: string[] = [];
  let current = "";
  for (const raw of text.split(/\s+/).filter(Boolean)) {
    const word = raw.length > maxChars ? `${raw.slice(0, maxChars - 1)}…` : raw;
    if (!current) current = word;
    else if (`${current} ${word}`.length <= maxChars) current = `${current} ${word}`;
    else {
      lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);
  if (lines.length <= maxLines) return lines;
  const kept = lines.slice(0, maxLines);
  kept[maxLines - 1] = `${kept[maxLines - 1].slice(0, maxChars - 1)}…`;
  return kept;
}

/** Deterministic layered layout. Returns null when there is nothing sensible
 * to draw (no nodes, or too many for a readable diagram) so the caller falls
 * back to the plain list. Edges whose endpoints don't exist are skipped. */
export function layoutArchitecture(
  nodes: readonly ArchitectureNode[],
  edges: readonly ArchitectureEdge[],
): ArchitectureLayout | null {
  const unique = nodes.filter((n, i) => nodes.findIndex((m) => m.id === n.id) === i);
  if (unique.length === 0 || unique.length > MAX_NODES) return null;

  const groups = GROUP_ORDER.filter((g) => unique.some((n) => n.group === g));
  const tallest = Math.max(...groups.map((g) => unique.filter((n) => n.group === g).length));
  const tallestHeight = tallest * NODE_H + (tallest - 1) * ROW_GAP;

  const columns = groups.map((group, i) => ({ group, x: PAD + i * (NODE_W + COL_GAP) }));
  const placed = new Map<string, PlacedNode & { col: number }>();
  groups.forEach((group, col) => {
    const members = unique.filter((n) => n.group === group);
    const offset = (tallestHeight - (members.length * NODE_H + (members.length - 1) * ROW_GAP)) / 2;
    members.forEach((node, row) => {
      placed.set(node.id, {
        node,
        col,
        x: columns[col].x,
        y: PAD + HEADER_H + offset + row * (NODE_H + ROW_GAP),
        lines: wrapLabel(node.label),
      });
    });
  });

  const placedEdges: PlacedEdge[] = [];
  for (const edge of edges) {
    const from = placed.get(edge.source);
    const to = placed.get(edge.target);
    if (!from || !to || from === to) continue;
    let x1: number, y1: number, x2: number, y2: number;
    if (from.col === to.col) {
      x1 = x2 = from.x + NODE_W / 2;
      [y1, y2] = to.y > from.y ? [from.y + NODE_H, to.y] : [from.y, to.y + NODE_H];
    } else if (from.col < to.col) {
      [x1, y1, x2, y2] = [from.x + NODE_W, from.y + NODE_H / 2, to.x, to.y + NODE_H / 2];
    } else {
      [x1, y1, x2, y2] = [from.x, from.y + NODE_H / 2, to.x + NODE_W, to.y + NODE_H / 2];
    }
    const mx = (x1 + x2) / 2;
    placedEdges.push({
      edge,
      path: from.col === to.col ? `M ${x1} ${y1} L ${x2} ${y2}` : `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`,
      labelX: mx,
      labelY: (y1 + y2) / 2,
    });
  }

  return {
    width: PAD * 2 + groups.length * NODE_W + (groups.length - 1) * COL_GAP,
    height: PAD * 2 + HEADER_H + tallestHeight,
    columns,
    nodes: [...placed.values()],
    edges: placedEdges,
  };
}
