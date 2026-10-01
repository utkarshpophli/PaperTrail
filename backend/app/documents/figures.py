"""Figure/table crop extraction with page number and caption.

Figures come from the PDF itself only, never from the web (ARCHITECTURE.md).
Each ``Figure N``/``Table N`` caption gets one rendered crop of everything
next to it (drawings and embedded images together; see
``vector_figures.py``). An embedded image outside every crop is kept as its
own figure only when it is figure-sized. Tiny icons and colorbars are parts
of a figure, not figures. Its caption comes from a proximity heuristic; see
the ``ponytail`` note on ``_find_caption`` for its quality ceiling.
"""

import re
from pathlib import Path

import fitz

from app.core.logging import get_logger
from app.documents.exceptions import DocumentUnreadableError
from app.documents.schemas import ParsedFigure
from app.documents.vector_figures import extract_vector_figures

logger = get_logger(__name__)

_CAPTION_PATTERN = re.compile(r"\bfig(?:ure)?\.?\s*\d+", re.IGNORECASE)
_ADJACENCY_TOLERANCE = 5.0  # points; blocks within this of the image edge count as adjacent
# ponytail: an image covering nearly the whole page is a scanned page
# background (or the OCR-source render), not a figure — a fixed fraction is
# a blunt cutoff (a genuine full-bleed figure would also be skipped).
# Upgrade path: revisit if that turns out to matter in practice.
_FULL_PAGE_IMAGE_AREA_FRACTION = 0.85
# An uncaptioned embedded image smaller than this on either side (points) is
# an icon, colorbar or logo, not a figure on its own.
_MIN_STANDALONE_IMAGE_SIDE = 60.0
# Bounds so a pathological PDF (thousands of embedded images or drawn
# captions) can't write an unbounded number of files.
MAX_FIGURES_PER_PAGE = 12
MAX_FIGURES_PER_PAPER = 60


def extract_figures(
    doc: fitz.Document,
    page: fitz.Page,
    page_number: int,
    output_dir: str,
    max_figures: int = MAX_FIGURES_PER_PAGE,
) -> list[ParsedFigure]:
    """Writes one crop per captioned figure/table on ``page`` to
    ``{output_dir}/figures/``, then any figure-sized embedded image outside
    those crops. At most ``max_figures`` (capped at the per-page limit) are
    returned; callers pass the remaining per-paper budget.
    """
    max_figures = min(max_figures, MAX_FIGURES_PER_PAGE)
    if max_figures <= 0:
        return []

    figures_dir = Path(output_dir) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    blocks = page.get_text("blocks")
    images = _placed_images(page)

    try:
        figures = extract_vector_figures(
            page, page_number, figures_dir, blocks, [tuple(r) for _, rects in images for r in rects], max_figures
        )
    except (RuntimeError, ValueError):
        # A malformed drawing stream must not cost the page its embedded images.
        logger.exception("captioned_figure_extraction_failed page=%d", page_number)
        figures = []

    crops = [fitz.Rect(f.bbox) for f in figures if f.bbox]
    crop_captions = {f.caption for f in figures}
    for index, (xref, rects) in enumerate(images):
        if len(figures) >= max_figures:
            break
        rect = max(rects, key=lambda r: r.width * r.height)  # largest placement
        if min(rect.width, rect.height) < _MIN_STANDALONE_IMAGE_SIDE or any(rect.intersects(c) for c in crops):
            continue

        try:
            extracted = doc.extract_image(xref)
            image_bytes = extracted["image"]
            ext = re.sub(r"[^a-z0-9]", "", extracted.get("ext", "png").lower()) or "png"
        except Exception:
            continue  # ponytail: one unreadable embedded image is skipped, not fatal to the page

        filename = f"page{page_number}_fig{index}.{ext}"
        (figures_dir / filename).write_bytes(image_bytes)
        caption = _find_caption(blocks, rect)
        figures.append(
            ParsedFigure(
                page=page_number,
                caption=None if caption in crop_captions else caption,
                image_path=f"figures/{filename}",
                bbox=tuple(rect),
            )
        )

    return figures


def _placed_images(page: fitz.Page) -> list[tuple[int, list[fitz.Rect]]]:
    """(xref, where it is drawn) for each embedded image actually placed on
    the page, minus full-page scans/backgrounds."""
    page_area = page.rect.width * page.rect.height
    placed: list[tuple[int, list[fitz.Rect]]] = []
    # get_images lists an image once per placement; get_image_rects already
    # returns every placement, so each xref is taken once.
    for xref in dict.fromkeys(img[0] for img in page.get_images(full=True)):
        rects = page.get_image_rects(xref)
        if not rects:
            continue
        if page_area > 0 and (rects[0].width * rects[0].height) / page_area >= _FULL_PAGE_IMAGE_AREA_FRACTION:
            continue  # full-page scan/background, not a figure
        placed.append((xref, rects))
    return placed


def extract_document_figures(pdf_path: str, output_dir: str) -> dict[int, list[ParsedFigure]]:
    """Re-runs figure extraction alone (no text/OCR) over a whole PDF,
    writing under ``{output_dir}/figures/``. Returns figures by 1-based page
    number for every page (empty list when none). A page that fails yields
    an empty list and a log line rather than aborting the rest.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        logger.error("figure_refresh_open_failed error=%s", type(exc).__name__)
        raise DocumentUnreadableError("Could not open PDF") from exc

    by_page: dict[int, list[ParsedFigure]] = {}
    total = 0
    with doc:
        for page_index in range(doc.page_count):
            page_number = page_index + 1
            try:
                found = extract_figures(doc, doc[page_index], page_number, output_dir, MAX_FIGURES_PER_PAPER - total)
            except Exception:
                logger.exception("figure_refresh_page_failed page=%d", page_number)
                found = []
            by_page[page_number] = found
            total += len(found)
    return by_page


def _find_caption(blocks: list[tuple], image_rect: fitz.Rect) -> str | None:
    # ponytail: proximity + regex heuristic, not real layout understanding.
    # Known ceiling: side-by-side subfigures, multi-image figures, and
    # captions more than one text block away will get no caption or the
    # wrong neighboring block's text. Upgrade path: a layout-aware parser
    # (marker/docling) if this proves too noisy in practice.
    below = sorted(
        (b for b in blocks if b[1] >= image_rect.y1 - _ADJACENCY_TOLERANCE),
        key=lambda b: b[1],
    )
    above = sorted(
        (b for b in blocks if b[3] <= image_rect.y0 + _ADJACENCY_TOLERANCE),
        key=lambda b: -b[3],
    )

    for candidates in (below, above):
        for block in candidates[:2]:
            text = block[4].strip()
            if _CAPTION_PATTERN.search(text):
                return text
    return None
