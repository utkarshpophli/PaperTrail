"use client";

import { useId, useRef, useState, type DragEvent } from "react";
import { FileText, UploadCloud, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export interface PaperSourceFieldProps {
  file: File | null;
  text: string;
  onFileChange: (file: File | null) => void;
  onTextChange: (text: string) => void;
  disabled?: boolean;
}

/** Either a PDF (drop or choose) or an arXiv id / URL / title. Picking one
 * clears the other so the source is never ambiguous. */
export function PaperSourceField({ file, text, onFileChange, onTextChange, disabled = false }: PaperSourceFieldProps) {
  const uid = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  function accept(candidate: File | undefined): void {
    if (!candidate) return;
    if (!isPdf(candidate)) {
      setFileError("Only PDF files can be uploaded.");
      return;
    }
    setFileError(null);
    onTextChange("");
    onFileChange(candidate);
  }

  function onDrop(event: DragEvent<HTMLLabelElement>): void {
    event.preventDefault();
    setDragging(false);
    if (!disabled) accept(event.dataTransfer.files[0]);
  }

  function clearFile(): void {
    onFileChange(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div className="flex flex-col gap-4">
      <label
        htmlFor={`${uid}-file`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors",
          dragging ? "border-brand bg-secondary" : "border-line-dark bg-background hover:bg-surface-2",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <UploadCloud className="size-6 text-ink-soft" aria-hidden="true" />
        <span className="text-body font-medium text-ink">Drop a PDF here, or choose one</span>
        <span className="text-caption text-muted-foreground">PDF only</span>
        <input
          id={`${uid}-file`}
          ref={inputRef}
          type="file"
          accept="application/pdf"
          disabled={disabled}
          onChange={(event) => accept(event.target.files?.[0])}
          className="sr-only"
        />
      </label>

      {fileError && (
        <p role="alert" className="text-body text-mismatch">
          {fileError}
        </p>
      )}

      {file && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-line bg-background px-3 py-2">
          <span className="flex min-w-0 items-center gap-2 text-body text-ink">
            <FileText className="size-4 shrink-0" aria-hidden="true" />
            <span className="truncate">{file.name}</span>
          </span>
          <Button type="button" variant="ghost" size="icon-sm" aria-label={`Remove ${file.name}`} onClick={clearFile} disabled={disabled}>
            <X />
          </Button>
        </div>
      )}

      <div className="flex items-center gap-3 text-caption uppercase tracking-wide text-muted-foreground" aria-hidden="true">
        <span className="h-px flex-1 bg-line" />
        or
        <span className="h-px flex-1 bg-line" />
      </div>

      <label className="flex flex-col gap-1 text-ui-label font-medium text-ink" htmlFor={`${uid}-arxiv`}>
        arXiv id, URL or title
        <input
          id={`${uid}-arxiv`}
          type="text"
          value={text}
          onChange={(event) => {
            if (file) clearFile();
            onTextChange(event.target.value);
          }}
          placeholder="1706.03762, https://arxiv.org/abs/1706.03762, or a paper title"
          autoComplete="off"
          disabled={disabled}
          className="rounded-md border border-input bg-background px-3 py-2 text-body font-normal text-ink disabled:opacity-60"
        />
      </label>
    </div>
  );
}
