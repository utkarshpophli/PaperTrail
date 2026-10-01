import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AppShell } from "./app-shell";
import { isActivePath, isStudioPath } from "./nav-items";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

afterEach(() => {
  pathname = "/";
});

describe("AppShell", () => {
  it("renders the top bar with brand, Home, Library and the local-mode indicator", () => {
    render(
      <AppShell>
        <p>page body</p>
      </AppShell>,
    );
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Paper Trail" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute("href", "/library");
    expect(screen.getAllByText("local · nothing leaves this machine").length).toBeGreaterThan(0);
    expect(screen.getByText("page body")).toBeInTheDocument();
  });

  it("links to none of the surfaces held back for a later release", () => {
    render(<AppShell>x</AppShell>);
    expect(screen.queryByRole("button", { name: "Explore" })).not.toBeInTheDocument();
    for (const name of ["Discover", "Roadmaps", "Collections", "Graph"]) {
      expect(screen.queryByRole("link", { name })).not.toBeInTheDocument();
    }
  });

  it("marks Library active on /library", () => {
    pathname = "/library";
    render(<AppShell>x</AppShell>);
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });

  it.each(["/papers/abc-123", "/papers/abc-123/anything"])("renders children bare, with no chrome, on %s", (path) => {
    pathname = path;
    render(
      <AppShell>
        <p>studio</p>
      </AppShell>,
    );
    expect(screen.getByText("studio")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
    expect(screen.queryByText(/nothing leaves this machine/)).not.toBeInTheDocument();
    expect(screen.queryByRole("main")).not.toBeInTheDocument();
  });

  it("keeps chrome on non-studio paths that merely start with /papers", () => {
    pathname = "/papers";
    render(<AppShell>x</AppShell>);
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
  });
});

describe("nav helpers", () => {
  it("isStudioPath matches only /papers/{id}...", () => {
    expect(isStudioPath("/papers/1")).toBe(true);
    expect(isStudioPath("/papers")).toBe(false);
    expect(isStudioPath("/papers/")).toBe(false);
    expect(isStudioPath("/library")).toBe(false);
  });

  it("isActivePath treats Home as exact and others as prefixes", () => {
    expect(isActivePath("/graph/x", "/graph")).toBe(true);
    expect(isActivePath("/graphic", "/graph")).toBe(false);
    expect(isActivePath("/library", "/")).toBe(false);
  });
});
