import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MilestoneItem } from "./milestone-item";
import type { Concept, Milestone, PrerequisiteEdge } from "@/lib/discovery-api";

const CONCEPTS: Concept[] = [
  {
    id: "concept-1",
    name: "Denoising",
    description: "Iteratively removing noise from a sample.",
    source_paper_id: null,
    source_arxiv_id: "1234.5678",
    grounding_excerpt: "we denoise the sample",
    verification_status: "verified",
  },
  {
    id: "concept-2",
    name: "Score matching",
    description: "Estimating the gradient of the log density.",
    source_paper_id: null,
    source_arxiv_id: "1234.5678",
    grounding_excerpt: "score matching estimates the gradient",
    verification_status: "needs-review",
  },
];

const EDGES: PrerequisiteEdge[] = [{ concept_id: "concept-1", prerequisite_concept_id: "concept-2" }];

function milestone(overrides: Partial<Milestone>): Milestone {
  return {
    id: "milestone-1",
    order: 1,
    paper_id: null,
    arxiv_id: null,
    title: "Score-based generative modeling",
    concept_ids: ["concept-1", "concept-2"],
    status: "available",
    ...overrides,
  };
}

describe("MilestoneItem", () => {
  it("disables the status control while locked, and shows a text/icon indicator", () => {
    render(
      <MilestoneItem milestone={milestone({ status: "locked" })} concepts={CONCEPTS} edges={EDGES} onStatusChange={vi.fn()} />,
    );
    expect(screen.getByRole("combobox", { name: /update milestone status/i })).toBeDisabled();
    expect(screen.getByTestId("milestone-status")).toHaveTextContent("Locked");
  });

  it("calls onStatusChange with the selected value when not locked", () => {
    const onStatusChange = vi.fn();
    render(
      <MilestoneItem milestone={milestone({ status: "available" })} concepts={CONCEPTS} edges={EDGES} onStatusChange={onStatusChange} />,
    );
    const select = screen.getByRole("combobox", { name: /update milestone status/i });
    expect(select).not.toBeDisabled();
    fireEvent.change(select, { target: { value: "completed" } });
    expect(onStatusChange).toHaveBeenCalledWith("completed");
  });

  it("links into the paper's existing page when paper_id is set (ingested)", () => {
    render(
      <MilestoneItem
        milestone={milestone({ paper_id: "paper-1", arxiv_id: null })}
        concepts={CONCEPTS}
        edges={EDGES}
        onStatusChange={vi.fn()}
      />,
    );
    const link = screen.getByRole("link", { name: "Open paper" });
    expect(link).toHaveAttribute("href", "/papers/paper-1");
  });

  it("links out to arXiv (new tab) when only arxiv_id is set (not ingested) -- never a fabricated in-app link", () => {
    render(
      <MilestoneItem
        milestone={milestone({ paper_id: null, arxiv_id: "1234.5678" })}
        concepts={CONCEPTS}
        edges={EDGES}
        onStatusChange={vi.fn()}
      />,
    );
    const link = screen.getByRole("link", { name: /open on arxiv/i });
    expect(link).toHaveAttribute("href", "https://arxiv.org/abs/1234.5678");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("resolves concept_ids against the roadmap's concepts, with verification badges and prerequisite names", () => {
    render(<MilestoneItem milestone={milestone({})} concepts={CONCEPTS} edges={EDGES} onStatusChange={vi.fn()} />);
    expect(screen.getByText("Denoising")).toBeInTheDocument();
    expect(screen.getByText("Score matching")).toBeInTheDocument();
    expect(screen.getByText("Requires: Score matching")).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
  });
});
