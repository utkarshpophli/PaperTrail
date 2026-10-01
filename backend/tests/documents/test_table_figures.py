"""Table-region tests against synthetic PDFs drawn with PyMuPDF."""

import fitz

from app.documents.table_figures import find_table_regions
from tests.documents.pdf_builders import add_caption, new_pdf


def _booktabs(page: fitz.Page, top: float, bottom: float, x0: float = 100, x1: float = 480) -> None:
    for y in (top, top + 20, bottom):
        page.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=0.5)


def _captions(page: fitz.Page) -> list[tuple[tuple[float, float, float, float], str]]:
    return [(tuple(b[:4]), b[4].strip()) for b in page.get_text("blocks") if b[4].startswith("Table")]


def test_caption_between_two_tables_pairs_with_its_own_side() -> None:
    """DeepSeek-V3 p34: Table 8's caption sits 10pt under its own table and
    6pt over Table 9's. Captions are below tables on this page, so both must
    pair upward rather than nearest-wins."""
    _, page = new_pdf()
    _booktabs(page, 80, 200)
    add_caption(page, 216, "Table 8: First")
    _booktabs(page, 226, 300, x0=120, x1=460)
    add_caption(page, 316, "Table 9: Second")

    regions = dict(find_table_regions(page, _captions(page)))

    assert regions["Table 8: First"][1] < 81 and regions["Table 8: First"][3] < 201
    assert regions["Table 9: Second"][1] > 225


def test_caption_above_table_is_supported() -> None:
    _, page = new_pdf()
    add_caption(page, 100, "Table 1: Caption on top")
    _booktabs(page, 110, 200)

    ((text, box),) = find_table_regions(page, _captions(page))

    assert text == "Table 1: Caption on top" and box[1] >= 109


def test_a_single_rule_is_not_a_table() -> None:
    _, page = new_pdf()
    page.draw_line((100, 190), (480, 190), color=(0, 0, 0), width=0.5)
    add_caption(page, 210, "Table 1: Just one rule")

    assert find_table_regions(page, _captions(page)) == []
