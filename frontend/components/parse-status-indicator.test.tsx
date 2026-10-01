import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ParseStatusIndicator } from "./parse-status-indicator";
import type { ParseStatus } from "@/lib/paper-types";

const CASES: Array<[ParseStatus, string]> = [
  ["pending", "Pending"],
  ["parsing", "Parsing…"],
  ["parsed", "Parsed"],
  ["failed", "Failed"],
];

describe("ParseStatusIndicator", () => {
  it.each(CASES)("renders the %s status with its text label (never color alone)", (status, label) => {
    render(<ParseStatusIndicator status={status} />);
    expect(screen.getByRole("status")).toHaveTextContent(label);
  });

  it.each(CASES)("renders an icon for %s", (status) => {
    const { container } = render(<ParseStatusIndicator status={status} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("shows the parse_error message when failed", () => {
    render(<ParseStatusIndicator status="failed" errorMessage="Corrupt PDF stream" />);
    expect(screen.getByRole("status")).toHaveTextContent("Corrupt PDF stream");
  });

  it("does not show an error message for non-failed statuses even if provided", () => {
    render(<ParseStatusIndicator status="parsed" errorMessage="stale leftover message" />);
    expect(screen.getByRole("status")).not.toHaveTextContent("stale leftover message");
  });

  it("applies a distinct color token per status", () => {
    const { rerender, getByRole } = render(<ParseStatusIndicator status="parsed" />);
    const parsedClass = getByRole("status").className;
    rerender(<ParseStatusIndicator status="failed" />);
    const failedClass = getByRole("status").className;
    expect(parsedClass).not.toEqual(failedClass);
  });
});
