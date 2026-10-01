import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { OpencodeHandoffPanel } from "./opencode-handoff-panel";
import { getOpencodeHandoff, type OpencodeHandoff } from "@/lib/coderesearch-api";
import { ApiRequestError } from "@/lib/api-types";
import { __resetSessionModeForTests, useSessionMode } from "@/lib/session-mode-store";

vi.mock("@/lib/coderesearch-api", () => ({ getOpencodeHandoff: vi.fn() }));

const HANDOFF: OpencodeHandoff = {
  filename: "paper-trail-handoff.md",
  markdown: "# Handoff\n\nUses multi-head attention (p. 3).",
  command: "opencode run --file paper-trail-handoff.md",
};

async function openHandoff(handoff: OpencodeHandoff = HANDOFF): Promise<void> {
  vi.mocked(getOpencodeHandoff).mockResolvedValueOnce(handoff);
  render(<OpencodeHandoffPanel paperId="paper-1" />);
  fireEvent.click(screen.getByRole("button", { name: "Hand off to OpenCode" }));
  await screen.findByText(handoff.command);
}

describe("OpencodeHandoffPanel", () => {
  beforeEach(() => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });
  afterEach(() => {
    __resetSessionModeForTests();
    vi.resetAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows the notice and caution before anything is fetched", () => {
    render(<OpencodeHandoffPanel paperId="paper-1" />);
    expect(
      screen.getByText(
        "Paper Trail does not run OpenCode. Download the file, put it in your own repository, and run the command on your own machine.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/marked as untrusted/)).toBeInTheDocument();
    expect(getOpencodeHandoff).not.toHaveBeenCalled();
  });

  it("fetches the handoff and renders the command and markdown preview", async () => {
    await openHandoff();
    expect(getOpencodeHandoff).toHaveBeenCalledWith("paper-1");
    expect(screen.getByText(HANDOFF.command).tagName).toBe("PRE");
    expect(screen.getByText(/Uses multi-head attention/).tagName).toBe("PRE");
  });

  it("copies the exact command", async () => {
    await openHandoff();
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(HANDOFF.command));
    expect(await screen.findByText("Copied.")).toBeInTheDocument();
  });

  it("shows a message when the clipboard is unavailable", async () => {
    await openHandoff();
    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(new Error("denied"));
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByText(/Copy failed/)).toBeInTheDocument();
  });

  it("downloads a Blob with the exact markdown and filename, then revokes the URL", async () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:handoff");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    let downloadName = "";
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloadName = this.download;
    });

    await openHandoff();
    fireEvent.click(screen.getByRole("button", { name: "Download context file" }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    expect(blob.type).toBe("text/markdown");
    expect(await blob.text()).toBe(HANDOFF.markdown);
    expect(downloadName).toBe(HANDOFF.filename);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:handoff");
    click.mockRestore();
  });

  it("renders script and event-handler markup literally as text", async () => {
    const hostile = '<script>alert(1)</script>\n<img src=x onerror="alert(2)">';
    await openHandoff({ ...HANDOFF, markdown: hostile });
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
    expect(document.body.querySelector("script")).toBeNull();
    expect(document.body.querySelector("img")).toBeNull();
  });

  it("tells the user to run the analysis first on evidence_not_found", async () => {
    vi.mocked(getOpencodeHandoff).mockRejectedValueOnce(
      new ApiRequestError(404, { code: "evidence_not_found", message: "raw backend text" }),
    );
    render(<OpencodeHandoffPanel paperId="paper-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Hand off to OpenCode" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Run the evidence analysis first.");
    expect(alert).not.toHaveTextContent("raw backend text");
  });

  it("handles paper_not_found and falls back to the backend message otherwise", async () => {
    vi.mocked(getOpencodeHandoff)
      .mockRejectedValueOnce(new ApiRequestError(404, { code: "paper_not_found", message: "nope" }))
      .mockRejectedValueOnce(new ApiRequestError(500, { code: "boom", message: "<b>Server exploded</b>" }));
    render(<OpencodeHandoffPanel paperId="paper-1" />);
    const button = screen.getByRole("button", { name: "Hand off to OpenCode" });

    fireEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("This paper no longer exists.");

    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("<b>Server exploded</b>"));
  });

  it("does not change the session indicator", async () => {
    const session = renderHook(() => useSessionMode());
    expect(session.result.current).toBe("local");
    await openHandoff();
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalled());
    expect(session.result.current).toBe("local");
  });
});
