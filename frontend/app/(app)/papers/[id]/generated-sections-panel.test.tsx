import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { GeneratedSectionsPanel } from "./generated-sections-panel";
import { ApiRequestError } from "@/lib/api-types";
import type { ClaimResponse, GeneratedSectionResponse } from "@/lib/evidence-api";
import { makeFigure } from "@/lib/studio-fixtures";

const claim: ClaimResponse = {
  id: "claim-1",
  statement: "The model achieves 92% accuracy.",
  kind: "reported-result",
  verification_status: "verified",
  source_refs: [{ id: "ref-1", page: 4, excerpt: "we achieve 92% accuracy", locator: null }],
  created_at: "2024-01-01T00:00:00Z",
};

const section: GeneratedSectionResponse = {
  id: "section-1",
  title: "Results",
  content: "The paper reports strong results.",
  order: 0,
  claim_ids: ["claim-1"],
  created_at: "2024-01-01T00:00:00Z",
};

describe("GeneratedSectionsPanel", () => {
  it("renders sections ordered, with claim links back to their sources", async () => {
    const fetchSections = vi.fn().mockResolvedValueOnce([section]);
    render(
      <GeneratedSectionsPanel
        title="Deep Report"
        paperId="paper-1"
        claims={[claim]}
        fetchSections={fetchSections}
        notFoundCode="report_not_found"
        refreshKey={0}
      />,
    );

    expect(await screen.findByText("Results")).toBeInTheDocument();
    expect(screen.getByText("The paper reports strong results.")).toBeInTheDocument();
    expect(screen.getByText(claim.statement)).toBeInTheDocument();
    expect(fetchSections).toHaveBeenCalledWith("paper-1");
  });

  it("shows a figure inline under the section that names it", async () => {
    const sections = [
      section,
      { ...section, id: "section-2", title: "Architecture", content: "Figure 2 shows the MoE routing.", order: 1, claim_ids: [] },
    ];
    const figure = makeFigure("page7_vec0.png", [], { label: "Figure 2", caption: "Figure 2 | Basic architecture" });
    render(
      <GeneratedSectionsPanel
        title="Primer"
        paperId="paper-1"
        claims={[claim]}
        fetchSections={vi.fn().mockResolvedValueOnce(sections)}
        notFoundCode="learning_not_found"
        refreshKey={0}
        figures={[figure]}
      />,
    );

    const architecture = (await screen.findByText("Architecture")).closest("li");
    expect(architecture).not.toBeNull();
    expect(within(architecture as HTMLElement).getByRole("img", { name: "Figure 2 | Basic architecture" })).toBeInTheDocument();
    const results = screen.getByText("Results").closest("li") as HTMLElement;
    expect(within(results).queryByRole("img")).toBeNull();
  });

  it("shows a calm not-generated-yet state on the matching 404 code, not an alarming error", async () => {
    const fetchSections = vi
      .fn()
      .mockRejectedValueOnce(new ApiRequestError(404, { code: "report_not_found", message: "Report not found" }));
    render(
      <GeneratedSectionsPanel
        title="Deep Report"
        paperId="paper-1"
        claims={[claim]}
        fetchSections={fetchSections}
        notFoundCode="report_not_found"
        refreshKey={0}
      />,
    );

    expect(await screen.findByText(/not generated yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("surfaces an unrelated failure as an alert", async () => {
    const fetchSections = vi
      .fn()
      .mockRejectedValueOnce(new ApiRequestError(500, { code: "internal_error", message: "Something broke" }));
    render(
      <GeneratedSectionsPanel
        title="Deep Report"
        paperId="paper-1"
        claims={[claim]}
        fetchSections={fetchSections}
        notFoundCode="report_not_found"
        refreshKey={0}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Something broke");
  });

  it("renders an h3 (not h2) title when nested inside a caller's own h2 panel, to avoid skipping/duplicating heading levels", async () => {
    const fetchSections = vi.fn().mockResolvedValueOnce([section]);
    render(
      <GeneratedSectionsPanel
        title="Primer"
        paperId="paper-1"
        claims={[claim]}
        fetchSections={fetchSections}
        notFoundCode="learning_not_found"
        refreshKey={0}
        headingLevel="h3"
      />,
    );

    expect(await screen.findByRole("heading", { level: 3, name: "Primer" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 4, name: "Results" })).toBeInTheDocument();
  });
});
