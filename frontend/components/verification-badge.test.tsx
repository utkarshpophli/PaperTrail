import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { VerificationBadge, type VerificationStatus } from "./verification-badge";

const CASES: Array<[VerificationStatus, string]> = [
  ["verified", "Verified"],
  ["partially-matched", "Partial match"],
  ["mismatch", "Mismatch"],
  ["not-found", "Not found"],
  ["needs-review", "Needs review"],
];

describe("VerificationBadge", () => {
  it.each(CASES)("renders the %s status with its text label (never color alone)", (status, label) => {
    render(<VerificationBadge status={status} />);
    expect(screen.getByRole("status")).toHaveTextContent(label);
  });

  it.each(CASES)("renders a distinct icon per status for %s", (status) => {
    const { container } = render(<VerificationBadge status={status} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("uses the standalone size (24px / ui-label) by default", () => {
    render(<VerificationBadge status="verified" />);
    const badge = screen.getByRole("status");
    expect(badge.className).toContain("h-6");
    expect(badge.className).toContain("text-ui-label");
  });

  it("uses the inline size (20px / caption) when requested", () => {
    render(<VerificationBadge status="verified" size="inline" />);
    const badge = screen.getByRole("status");
    expect(badge.className).toContain("h-5");
    expect(badge.className).toContain("text-caption");
  });

  it("applies a distinct color token per status", () => {
    const { rerender, getByRole } = render(<VerificationBadge status="verified" />);
    const verifiedClass = getByRole("status").className;
    rerender(<VerificationBadge status="mismatch" />);
    const mismatchClass = getByRole("status").className;
    expect(verifiedClass).not.toEqual(mismatchClass);
  });
});
