import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DemoBanner } from "./demo-banner";

describe("DemoBanner", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("renders nothing outside the hosted demo build", () => {
    const { container } = render(<DemoBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("warns that the demo workspace is shared and how keys are handled", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "1");
    render(<DemoBanner />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("visible to other visitors");
    expect(note).toHaveTextContent("never stored");
    expect(screen.getByRole("link", { name: /run it on your own machine/i })).toHaveAttribute(
      "href",
      "https://github.com/utkarshpophli/PaperTrail",
    );
  });
});
