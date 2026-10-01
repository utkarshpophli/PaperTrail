/** A new-paper source chosen in the composer: a PDF, an arXiv id (typed or
 * pulled out of an arxiv.org URL), or a title to search for. */
export type PaperSource =
  | { kind: "file"; file: File }
  | { kind: "arxiv"; arxivId: string }
  | { kind: "title"; title: string };

// New-style ids (2405.01234, optional version) and old-style (hep-th/9901001).
const NEW_ID = String.raw`\d{4}\.\d{4,5}(?:v\d+)?`;
const OLD_ID = String.raw`[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?`;
const BARE_ID = new RegExp(`^(?:arxiv:)?(${NEW_ID}|${OLD_ID})$`, "i");
const URL_ID = new RegExp(`^(${NEW_ID}|${OLD_ID})$`, "i");

/**
 * Returns the arXiv id for a bare id ("1706.03762", "arXiv:1706.03762v5") or
 * an arxiv.org abs/pdf URL (with or without ".pdf" or a version); null for
 * anything else (which the caller treats as a title search).
 */
export function extractArxivId(input: string): string | null {
  const text = input.trim();
  const bare = BARE_ID.exec(text);
  if (bare) return bare[1];

  let url: URL;
  try {
    url = new URL(/^https?:\/\//i.test(text) ? text : `https://${text}`);
  } catch {
    return null;
  }
  if (url.hostname !== "arxiv.org" && !url.hostname.endsWith(".arxiv.org")) return null;
  const match = /^\/(?:abs|pdf|html)\/(.+?)(?:\.pdf)?\/?$/.exec(url.pathname);
  const id = match ? URL_ID.exec(match[1]) : null;
  return id ? id[1] : null;
}

/** File beats text; blank text means no source yet. */
export function toPaperSource(file: File | null, text: string): PaperSource | null {
  if (file) return { kind: "file", file };
  const trimmed = text.trim();
  if (!trimmed) return null;
  const arxivId = extractArxivId(trimmed);
  return arxivId ? { kind: "arxiv", arxivId } : { kind: "title", title: trimmed };
}
