import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeClaim } from "@/lib/studio-fixtures";
import { EMPTY_DRAWER_TEXT, EvidenceDrawer } from "./evidence-drawer";

const reverify = vi.hoisted(() => vi.fn());
vi.mock("@/lib/evidence-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/evidence-api")>()),
  reverifyClaim: reverify,
}));

const claim = makeClaim("abc", { statement: "BLEU improves", status: "partially-matched", pages: [3, 7], excerpt: "achieves 28.4 BLEU\nsecond line" });

afterEach(() => vi.clearAllMocks());

function renderDrawer(overrides: Partial<Parameters<typeof EvidenceDrawer>[0]> = {}) {
  const props = { claim, paperId: "p1", variant: "docked" as const, onClose: vi.fn(), onClaimUpdated: vi.fn(), ...overrides };
  return { props, ...render(<EvidenceDrawer {...props} />) };
}

describe("EvidenceDrawer", () => {
  it("shows the empty-state guidance with no claim", () => {
    renderDrawer({ claim: null });
    expect(screen.getByText(EMPTY_DRAWER_TEXT)).toBeInTheDocument();
  });

  it("renders nothing for the overlay variant with no claim", () => {
    renderDrawer({ claim: null, variant: "overlay" });
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("shows status as text with an icon, the kind, the statement heading and one card per source ref", () => {
    const { container } = renderDrawer();
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Partial match");
    expect(status.querySelector("svg")).not.toBeNull();
    expect(screen.getByText("Reported result")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "BLEU improves" })).toBeInTheDocument();
    expect(screen.getByText("Page 3")).toBeInTheDocument();
    expect(screen.getByText("Page 7")).toBeInTheDocument();
    const quotes = container.querySelectorAll("blockquote");
    expect(quotes).toHaveLength(2);
    expect(quotes[0].textContent).toBe("achieves 28.4 BLEU\nsecond line");
  });

  it("copies a #claim-<id> permalink", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText.mock.calls[0][0]).toMatch(/#claim-abc$/);
    expect(await screen.findByText("Link copied")).toBeInTheDocument();
  });

  it("reports a failed copy instead of failing silently", async () => {
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }, configurable: true });
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    expect(await screen.findByText("Could not copy the link")).toBeInTheDocument();
  });

  it("closes on Escape and via the close button", () => {
    const { props } = renderDrawer({ variant: "overlay" });
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close evidence" }));
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("re-verifies through the backend and hands the updated claim up", async () => {
    const updated = { ...claim, verification_status: "verified" as const };
    reverify.mockResolvedValueOnce(updated);
    const { props } = renderDrawer();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Re-verify" }));
    });
    expect(reverify).toHaveBeenCalledWith("p1", "abc");
    expect(props.onClaimUpdated).toHaveBeenCalledWith(updated);
  });

  it("surfaces a re-verify failure", async () => {
    reverify.mockRejectedValueOnce(new Error("verifier down"));
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Re-verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("verifier down");
  });
});
