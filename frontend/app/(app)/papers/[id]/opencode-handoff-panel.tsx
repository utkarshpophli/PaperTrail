"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api-types";
import { getOpencodeHandoff, type OpencodeHandoff } from "@/lib/coderesearch-api";

const HANDOFF_NOTICE =
  "Paper Trail does not run OpenCode. Download the file, put it in your own repository, and run the command on your own machine.";
const HANDOFF_CAUTION =
  "The file contains text extracted from the paper, marked as untrusted. Review it, and keep OpenCode's permissions restrictive (no auto-approve) when the paper isn't yours.";

/** Rendered only as React text, never as HTML. */
function handoffFailureMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.code === "evidence_not_found") return "Run the evidence analysis first.";
    if (error.code === "paper_not_found") return "This paper no longer exists.";
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

function saveTextFile(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function OpencodeHandoffPanel({ paperId }: { paperId: string }) {
  const [handoff, setHandoff] = useState<OpencodeHandoff | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  async function handleFetch(): Promise<void> {
    setBusy(true);
    setError(null);
    setCopyStatus(null);
    try {
      setHandoff(await getOpencodeHandoff(paperId));
    } catch (failure: unknown) {
      setHandoff(null);
      setError(handoffFailureMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  async function handleCopy(command: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(command);
      setCopyStatus("Copied.");
    } catch {
      setCopyStatus("Copy failed. Select the command and copy it manually.");
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Hand off to OpenCode</h2>
      <p className="text-caption font-medium text-foreground">{HANDOFF_NOTICE}</p>
      <p className="text-caption text-muted-foreground">
        <span aria-hidden="true">⚠ </span>
        {HANDOFF_CAUTION}
      </p>

      <div>
        <Button type="button" size="sm" onClick={() => void handleFetch()} disabled={busy}>
          {busy ? "Preparing…" : "Hand off to OpenCode"}
        </Button>
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-mismatch-bg px-3 py-2 text-body text-mismatch">
          {error}
        </p>
      )}

      {handoff && (
        <div className="flex flex-col gap-3">
          <pre className="whitespace-pre-wrap break-all rounded-md border border-border bg-background p-2 font-mono text-mono text-foreground">
            {handoff.command}
          </pre>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => void handleCopy(handoff.command)}>
              Copy
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => saveTextFile(handoff.filename, handoff.markdown)}
            >
              Download context file
            </Button>
            {copyStatus && (
              <span role="status" className="text-caption text-muted-foreground">
                {copyStatus}
              </span>
            )}
          </div>
          <details className="rounded-md border border-border bg-background p-2">
            <summary className="cursor-pointer text-ui-label text-foreground">Preview context file</summary>
            {/* Embeds untrusted paper text: plain text only. */}
            <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono text-mono text-foreground">
              {handoff.markdown}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}
