import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { StudioTopBar } from "./studio-top-bar";
import { __resetSessionModeForTests } from "@/lib/session-mode-store";

describe("StudioTopBar", () => {
  afterEach(() => {
    __resetSessionModeForTests();
  });

  // The full indicator is "hidden lg:block" and the collapsed one is
  // "lg:hidden" — jsdom doesn't apply either media query, so both render.
  // A regression here (e.g. only the "hidden lg:block" copy present) would
  // mean the indicator is invisible on any viewport under the lg breakpoint,
  // on the one page where AppShell's own copy is deliberately suppressed.
  it("renders both the full and collapsed local-mode indicator, so one is always visible regardless of viewport", () => {
    render(<StudioTopBar title="A Paper" mode="lab" onModeChange={vi.fn()} />);
    const indicators = screen.getAllByTitle("local · nothing leaves this machine");
    expect(indicators.length).toBe(2);
    expect(screen.getByText("local · nothing leaves this machine")).toBeInTheDocument();
  });
});
