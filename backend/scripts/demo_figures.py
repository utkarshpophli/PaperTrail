"""Draws the three demo figures with PyMuPDF (already a dependency): simple
labelled diagrams, each stamped as illustrative. The only numbers drawn are
the three accuracy values already in the demo paper's text."""

from pathlib import Path

import fitz

_W, _H = 640, 400
_INK = (0.13, 0.12, 0.11)
_ACCENT = (0.75, 0.32, 0.18)
_PAPER = (0.98, 0.96, 0.92)
_MUTED = (0.55, 0.52, 0.48)


def _canvas() -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    page = doc.new_page(width=_W, height=_H)
    page.draw_rect(page.rect, color=None, fill=_PAPER)
    page.insert_text((14, _H - 12), "ILLUSTRATIVE DEMO FIGURE - not real data", fontsize=9, color=_MUTED)
    return doc, page


def _box(page: fitz.Page, rect: fitz.Rect, label: str, *, fill: tuple[float, float, float] | None = None) -> None:
    page.draw_rect(rect, color=_INK, fill=fill, width=1.5)
    page.insert_textbox(rect + (4, rect.height / 2 - 8, -4, 0), label, fontsize=12, color=_INK, align=fitz.TEXT_ALIGN_CENTER)


def _arrow(page: fitz.Page, start: fitz.Point, end: fitz.Point) -> None:
    page.draw_line(start, end, color=_INK, width=1.5)
    page.draw_circle(end, 3, color=_INK, fill=_INK)


def _save(doc: fitz.Document, page: fitz.Page, path: Path) -> None:
    page.get_pixmap(dpi=110).save(path)
    doc.close()


def _architecture(path: Path) -> None:
    doc, page = _canvas()
    labels = ["Tokens", "Token encoder", "Router", "Expert blocks", "Output"]
    for index, label in enumerate(labels):
        rect = fitz.Rect(20 + index * 122, 150, 120 + index * 122, 210)
        _box(page, rect, label, fill=_ACCENT if label == "Router" else None)
        if index:
            _arrow(page, fitz.Point(rect.x0 - 22, 180), fitz.Point(rect.x0, 180))
    _save(doc, page, path)


def _accuracy_bars(path: Path) -> None:
    doc, page = _canvas()
    bars = [("Dense", 79.5), ("Static pruning", 81.0), ("LatticeNet", 84.2)]
    for index, (label, value) in enumerate(bars):
        height = (value - 70) * 15
        x = 90 + index * 170
        page.draw_rect(fitz.Rect(x, 340 - height, x + 100, 340), color=_INK, fill=_ACCENT if label == "LatticeNet" else _MUTED)
        page.insert_text((x + 24, 334 - height), f"{value}", fontsize=14, color=_INK)
        page.insert_text((x, 362), label, fontsize=12, color=_INK)
    page.insert_text((14, 22), "Accuracy on the illustrative benchmark (axis starts at 70)", fontsize=11, color=_INK)
    _save(doc, page, path)


def _routing(path: Path) -> None:
    doc, page = _canvas()
    _box(page, fitz.Rect(20, 170, 130, 230), "Token")
    _box(page, fitz.Rect(190, 170, 300, 230), "Router", fill=_ACCENT)
    experts = [fitz.Rect(400, 40 + i * 78, 540, 88 + i * 78) for i in range(4)]
    for index, rect in enumerate(experts):
        _box(page, rect, f"Expert {index + 1}", fill=_ACCENT if index in (1, 2) else None)
        _arrow(page, fitz.Point(300, 200), fitz.Point(rect.x0, rect.y0 + 24))
    _arrow(page, fitz.Point(130, 200), fitz.Point(190, 200))
    page.insert_text((300, 24), "Top two experts (filled) run", fontsize=11, color=_INK)
    _save(doc, page, path)


def draw_figures(figures_dir: Path) -> None:
    """Writes ``page1_fig0.png``, ``page2_fig0.png``, ``page3_fig0.png``."""
    _architecture(figures_dir / "page1_fig0.png")
    _accuracy_bars(figures_dir / "page2_fig0.png")
    _routing(figures_dir / "page3_fig0.png")
