"""PDF -> page text/layout extraction.

PyMuPDF (``fitz``) is the primary text/layout extractor. OCR (``pytesseract``
on Tesseract) is a fallback for pages with no usable text layer (scanned
pages) — requires the system Tesseract binary, see docs/DEVELOPMENT.md.

Never calls an LLM (ARCHITECTURE.md: Document Pipeline). Never raises on a
single bad page: a page that fails entirely gets ``text=""`` and its number
is recorded in ``metadata['unparsed_pages']`` so the caller can surface the
gap instead of silently losing it.
"""

from typing import Any

import fitz
import pytesseract
from PIL import Image

from app.core.logging import get_logger
from app.documents.exceptions import DocumentUnreadableError
from app.documents.figures import MAX_FIGURES_PER_PAPER, extract_figures
from app.documents.schemas import ParsedDocument, ParsedPage

logger = get_logger(__name__)

# ponytail: "usable text layer" is a plain length check, not a real
# text-vs-image area ratio. A legitimately sparse page (e.g. a title-only
# page) also triggers OCR, which just re-derives the same sparse text at
# extra cost rather than producing wrong output. Upgrade path: compare text
# bbox area to page area via page.get_text("dict") if this misfires.
MIN_TEXT_LENGTH_BEFORE_OCR = 20
OCR_RENDER_DPI = 300


def parse_pdf(file_path: str, output_dir: str) -> ParsedDocument:
    """Parses the PDF at ``file_path``. Extracted figure images are written
    under ``output_dir``. See module docstring for the per-page error
    contract.
    """
    try:
        doc = fitz.open(file_path)
    except Exception as exc:
        raise DocumentUnreadableError(f"Could not open PDF: {exc}") from exc

    if doc.page_count == 0:
        doc.close()
        raise DocumentUnreadableError("PDF has zero pages")

    pages: list[ParsedPage] = []
    unparsed_pages: list[int] = []
    figure_count = 0

    for page_index in range(doc.page_count):
        page_number = page_index + 1
        try:
            page = doc[page_index]
            # Plain (unsorted) extraction, confirmed against a real
            # two-column ACL paper fixture: PyMuPDF's content-stream order
            # keeps each column's paragraphs together for LaTeX-produced
            # two-column PDFs. ``sort=True`` looked appealing but actually
            # interleaves left/right column lines that share a y-coordinate
            # — measured worse on the same fixture, so deliberately not used.
            text = _strip_nul_bytes(page.get_text())
            if len(text.strip()) < MIN_TEXT_LENGTH_BEFORE_OCR:
                ocr_text = _strip_nul_bytes(_ocr_page(page))
                if ocr_text.strip():
                    text = ocr_text
            figures = extract_figures(doc, page, page_number, output_dir, MAX_FIGURES_PER_PAPER - figure_count)
        except Exception:
            logger.exception("page_parse_failed file_path=%s page=%d", file_path, page_number)
            text = ""
            figures = []
            unparsed_pages.append(page_number)

        figure_count += len(figures)
        pages.append(ParsedPage(number=page_number, text=text, figures=figures))

    metadata: dict[str, Any] = dict(doc.metadata or {})
    metadata["page_count"] = doc.page_count
    metadata["unparsed_pages"] = unparsed_pages
    doc.close()

    return ParsedDocument(pages=pages, metadata=metadata)


def _strip_nul_bytes(text: str) -> str:
    """Postgres text columns reject ``\\x00`` outright regardless of
    encoding -- confirmed live: PyMuPDF's text extraction embeds a NUL byte
    for some fonts/ligatures (e.g. arXiv:2412.19437's page 1), which
    otherwise reaches the DB insert unsanitized and fails the whole parse."""
    return text.replace("\x00", "")


def _ocr_page(page: fitz.Page) -> str:
    pixmap = page.get_pixmap(dpi=OCR_RENDER_DPI)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    return pytesseract.image_to_string(image)
