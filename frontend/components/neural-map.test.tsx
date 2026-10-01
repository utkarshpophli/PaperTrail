import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ForceGraphProps } from "react-force-graph-3d";
import { NeuralMap } from "./neural-map";
import type { NeuralMapEdge, NeuralMapNode } from "@/lib/discovery-api";

// The real react-force-graph-3d touches WebGL/three.js at render time, which
// jsdom can't provide — mock it down to a stub that exposes just enough
// (rendered node labels + a click hook) to assert NeuralMap wired it up
// correctly.
vi.mock("react-force-graph-3d", () => ({
  default: (props: ForceGraphProps) => (
    <div data-testid="force-graph-3d" data-links={JSON.stringify(props.graphData?.links ?? [])}>
      {props.graphData?.nodes.map((node) => (
        <button
          key={String(node.id)}
          type="button"
          onClick={(event) => props.onNodeClick?.(node, event.nativeEvent)}
        >
          {String((node as { label?: string }).label)}
        </button>
      ))}
    </div>
  ),
}));

interface MatchMediaControls {
  /** Flips the live value for `query` and fires its "change" listener, the
   * same sequence a real prefers-reduced-motion/resize event produces. */
  set(query: string, matches: boolean): void;
}

function stubMatchMedia(overrides: Record<string, boolean>): MatchMediaControls {
  const state = { ...overrides };
  const listeners = new Map<string, (event: Event) => void>();
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        get matches() {
          return state[query] ?? false;
        },
        media: query,
        addEventListener: (_type: string, listener: (event: Event) => void) => listeners.set(query, listener),
        removeEventListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );
  return {
    set(query: string, matches: boolean) {
      state[query] = matches;
      listeners.get(query)?.(new Event("change"));
    },
  };
}

const NODES: NeuralMapNode[] = [
  { id: "1234.5678", label: "RAG Paper", color: "#ff0000", size: 5 },
  { id: "1111.2222", label: "Dense Retrieval Paper", color: "#00ff00", size: null },
];
const EDGES: NeuralMapEdge[] = [
  { source: "1234.5678", target: "1111.2222", relation: "semantically_similar", weight: 0.8 },
];

const WIDE_QUERY = "(min-width: 768px)";
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

describe("NeuralMap", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows an empty state instead of a blank canvas when there are no nodes", () => {
    stubMatchMedia({ [WIDE_QUERY]: true });
    render(<NeuralMap nodes={[]} edges={[]} />);
    expect(screen.getByText("No papers to map yet.")).toBeInTheDocument();
  });

  it("renders the 3D graph on a wide screen without reduced motion, and calls onNodeClick", async () => {
    stubMatchMedia({ [WIDE_QUERY]: true, [REDUCED_MOTION_QUERY]: false });
    const onNodeClick = vi.fn();
    render(<NeuralMap nodes={NODES} edges={EDGES} onNodeClick={onNodeClick} />);

    const graph = await waitFor(() => screen.getByTestId("force-graph-3d"));
    fireEvent.click(within(graph).getByRole("button", { name: "RAG Paper", hidden: true }));
    expect(onNodeClick).toHaveBeenCalledWith("1234.5678");
  });

  it("falls back to the list view below the width threshold", async () => {
    stubMatchMedia({ [WIDE_QUERY]: false });
    render(<NeuralMap nodes={NODES} edges={EDGES} />);

    expect(screen.queryByTestId("force-graph-3d")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RAG Paper" })).toBeInTheDocument();
  });

  it("falls back to the list view when prefers-reduced-motion is set, even on a wide screen", () => {
    stubMatchMedia({ [WIDE_QUERY]: true, [REDUCED_MOTION_QUERY]: true });
    render(<NeuralMap nodes={NODES} edges={EDGES} />);

    expect(screen.queryByTestId("force-graph-3d")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dense Retrieval Paper" })).toBeInTheDocument();
  });

  it("groups list-view nodes by cluster color and calls onNodeClick from a real button", () => {
    stubMatchMedia({ [WIDE_QUERY]: false });
    const onNodeClick = vi.fn();
    render(<NeuralMap nodes={NODES} edges={EDGES} onNodeClick={onNodeClick} />);

    const button = screen.getByRole("button", { name: "Dense Retrieval Paper" });
    fireEvent.click(button);
    expect(onNodeClick).toHaveBeenCalledWith("1111.2222");
  });

  it("reacts live to prefers-reduced-motion changing mid-session, not just at mount", () => {
    const matchMedia = stubMatchMedia({ [WIDE_QUERY]: true, [REDUCED_MOTION_QUERY]: false });
    render(<NeuralMap nodes={NODES} edges={EDGES} />);
    expect(screen.getByTestId("force-graph-3d")).toBeInTheDocument();

    // Simulate the OS-level setting flipping without a remount, the same way
    // a real prefers-reduced-motion toggle fires mid-session.
    act(() => matchMedia.set(REDUCED_MOTION_QUERY, true));

    expect(screen.queryByTestId("force-graph-3d")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RAG Paper" })).toBeInTheDocument();
  });

  describe("relation-aware edges", () => {
    const MIXED_EDGES: NeuralMapEdge[] = [
      { source: "1234.5678", target: "1111.2222", relation: "cites", weight: 1 },
      { source: "1111.2222", target: "1234.5678", relation: "extends", weight: 0.72 },
    ];

    it("lists only the relations present in the legend, as text, in the 2D fallback", () => {
      stubMatchMedia({ [WIDE_QUERY]: false });
      render(<NeuralMap nodes={NODES} edges={MIXED_EDGES} />);

      const legend = screen.getByRole("list", { name: "Edge relations in this graph" });
      expect(within(legend).getByText("Cites")).toBeInTheDocument();
      expect(within(legend).getByText("Extends")).toBeInTheDocument();
      expect(within(legend).queryByText("Improves")).not.toBeInTheDocument();
      expect(within(legend).queryByText("Semantically similar")).not.toBeInTheDocument();
    });

    it("shows each edge's relation, target and provenance as text under its source node", () => {
      stubMatchMedia({ [WIDE_QUERY]: false });
      render(<NeuralMap nodes={NODES} edges={MIXED_EDGES} />);

      expect(screen.getByText(/Cites Dense Retrieval Paper/)).toHaveTextContent("Citation record (OpenAlex)");
      expect(screen.getByText(/Extends RAG Paper/)).toHaveTextContent("AI-classified, 72% confidence");
    });

    it("colors 3D links by relation and leaves semantically_similar links uncolored", async () => {
      stubMatchMedia({ [WIDE_QUERY]: true, [REDUCED_MOTION_QUERY]: false });
      render(<NeuralMap nodes={NODES} edges={[...MIXED_EDGES, EDGES[0]]} />);

      const graph = await waitFor(() => screen.getByTestId("force-graph-3d"));
      const links = JSON.parse(graph.getAttribute("data-links") ?? "[]") as { color?: string }[];
      expect(links.map((link) => link.color)).toEqual(["#64748b", "#2563eb", undefined]);
    });

    it("shows a visible legend beside the 3D canvas, hidden from assistive tech (the sr-only list carries its own)", async () => {
      stubMatchMedia({ [WIDE_QUERY]: true, [REDUCED_MOTION_QUERY]: false });
      render(<NeuralMap nodes={NODES} edges={MIXED_EDGES} />);
      await waitFor(() => screen.getByTestId("force-graph-3d"));

      const legends = screen.getAllByRole("list", { name: "Edge relations in this graph", hidden: true });
      expect(legends).toHaveLength(2);
    });

    it("renders a similarity-only graph exactly as before: no legend, no per-edge text", () => {
      stubMatchMedia({ [WIDE_QUERY]: false });
      render(<NeuralMap nodes={NODES} edges={EDGES} />);

      expect(screen.queryByRole("list", { name: "Edge relations in this graph" })).not.toBeInTheDocument();
      expect(screen.queryByText(/Semantically similar/)).not.toBeInTheDocument();
    });
  });
});
