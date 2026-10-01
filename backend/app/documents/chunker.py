"""Page-aware chunking for embedding and evidence-pass context windows.

Chunks are sized in characters, not tokens: this module must never import a
tokenizer/provider dependency (ARCHITECTURE.md — document parsing never
touches AI provider code), and ~1000 characters of English prose is roughly
200-250 tokens, a reasonable embedding-window size without needing one. A
chunk never crosses a page boundary — chunking runs independently per page,
and each chunk carries the page it came from plus its offset within that
page's text so downstream code (Evidence Engine, Phase 2) can locate it
without re-searching.
"""

from pydantic import BaseModel

from app.documents.schemas import ParsedDocument

DEFAULT_CHUNK_SIZE_CHARS = 1000


class Chunk(BaseModel):
    page: int
    text: str
    start_char: int  # offset into that page's own text, not the whole document
    end_char: int


def chunk_document(document: ParsedDocument, chunk_size: int = DEFAULT_CHUNK_SIZE_CHARS) -> list[Chunk]:
    """Splits every page's text into chunks of at most ``chunk_size``
    characters, breaking at whitespace where possible.
    """
    chunks: list[Chunk] = []
    for page in document.pages:
        for start, end, text in _chunk_text(page.text, chunk_size):
            chunks.append(Chunk(page=page.number, text=text, start_char=start, end_char=end))
    return chunks


def _chunk_text(text: str, chunk_size: int) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    length = len(text)
    start = 0
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            split_at = text.rfind(" ", start, end)
            if split_at > start:
                end = split_at
        chunk_text = text[start:end].strip()
        if chunk_text:
            spans.append((start, end, chunk_text))
        start = end
        while start < length and text[start].isspace():
            start += 1
    return spans
