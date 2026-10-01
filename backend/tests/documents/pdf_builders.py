"""Synthetic PDFs built with PyMuPDF so vector-figure tests control exactly
what is drawn (real vector paths, real text) without shipping binary fixtures.
"""

import fitz

_LOREM = (
    "Neural sequence transduction models have an encoder and a decoder. "
    "The encoder maps an input sequence to a sequence of continuous representations. "
    "Given those representations the decoder generates an output sequence one element at a time. "
) * 3


def new_pdf(width: float = 612, height: float = 792) -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    return doc, doc.new_page(width=width, height=height)


def add_body(page: fitz.Page, top: float, bottom: float, left: float = 72, right: float = 540) -> None:
    remaining = page.insert_textbox(fitz.Rect(left, top, right, bottom), _LOREM, fontsize=10)
    assert remaining >= 0, "body text did not fit its box"


def draw_diagram(page: fitz.Page, x: float, y: float, w: float = 300, h: float = 150) -> None:
    """Three filled boxes joined by arrows plus a curve and a circle: >= 6
    drawing items with real (non-hairline) shapes."""
    box_w = w / 4
    for i in range(3):
        left = x + i * (w / 3) + 5
        page.draw_rect(fitz.Rect(left, y + 20, left + box_w, y + 70), color=(0, 0, 0), fill=(0.85, 0.9, 1))
        page.insert_text((left + 5, y + 50), f"Block {i}", fontsize=8)
    page.draw_line((x + box_w + 5, y + 45), (x + w / 3, y + 45), color=(0, 0, 0))
    page.draw_line((x + w / 3 + box_w + 5, y + 45), (x + 2 * w / 3, y + 45), color=(0, 0, 0))
    page.draw_bezier(
        (x + 10, y + h - 20), (x + w / 3, y + h), (x + 2 * w / 3, y + 80), (x + w - 10, y + h - 20), color=(0.6, 0, 0)
    )
    page.draw_circle((x + w / 2, y + 100), 12, color=(0, 0, 0), fill=(1, 0.8, 0.8))


def add_caption(page: fitz.Page, y: float, text: str, x: float = 72) -> None:
    page.insert_text((x, y), text, fontsize=10)


def vector_figure_pdf(path: str) -> None:
    """One page: body text, a drawn diagram, then a 'Figure 1' caption below."""
    doc, page = new_pdf()
    add_body(page, 60, 190)
    draw_diagram(page, 100, 230)
    add_caption(page, 410, "Figure 1: Overview of the model")
    add_body(page, 440, 580)
    doc.save(path)
    doc.close()


def png_bytes() -> bytes:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 80), False)
    pixmap.set_rect(pixmap.irect, (30, 90, 200))
    return pixmap.tobytes("png")
