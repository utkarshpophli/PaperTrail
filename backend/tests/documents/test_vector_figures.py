"""Vector-figure fallback tests against synthetic PDFs drawn with PyMuPDF."""

from pathlib import Path

import fitz
from PIL import Image

from app.documents import vector_figures
from app.documents.figures import (
    MAX_FIGURES_PER_PAGE,
    MAX_FIGURES_PER_PAPER,
    extract_document_figures,
    extract_figures,
)
from app.documents.parser import parse_pdf
from app.documents.vector_figures import _MAX_CAPTIONS_PER_PAGE, extract_vector_figures
from tests.documents.pdf_builders import (
    add_body,
    add_caption,
    draw_diagram,
    new_pdf,
    png_bytes,
    vector_figure_pdf,
)


def _extract(doc: fitz.Document, tmp_path: Path, page_index: int = 0, **kwargs: int):
    return extract_figures(doc, doc[page_index], page_index + 1, str(tmp_path), **kwargs)


def test_drawn_diagram_above_caption_becomes_vec_png(tmp_path: Path) -> None:
    pdf = tmp_path / "vec.pdf"
    vector_figure_pdf(str(pdf))

    parsed = parse_pdf(str(pdf), str(tmp_path / "out"))

    figures = parsed.pages[0].figures
    assert len(figures) == 1
    figure = figures[0]
    assert figure.caption == "Figure 1: Overview of the model"
    assert figure.image_path == "figures/page1_vec0.png"
    image_file = tmp_path / "out" / figure.image_path
    assert image_file.stat().st_size > 0
    with Image.open(image_file) as img:
        assert 200 < img.width < 1300 and 100 < img.height < 1300
    x0, y0, x1, y1 = figure.bbox
    assert y1 < 402  # stops above the caption text
    assert y0 > 190  # and below the body paragraph above it
    assert x1 - x0 > 250


def test_ruled_table_becomes_one_table_crop_and_no_figure(tmp_path: Path) -> None:
    doc, page = new_pdf()
    add_body(page, 60, 200)
    for i in range(5):  # a gridded table: axis-aligned hairlines only
        page.draw_line((72, 240 + i * 20), (400, 240 + i * 20), color=(0, 0, 0), width=0.5)
    for j in range(4):
        page.draw_line((72 + j * 110, 240), (72 + j * 110, 320), color=(0, 0, 0), width=0.5)
    add_caption(page, 345, "Table 1: Results")
    add_caption(page, 375, "Figure 1: Nothing is drawn here except the table above")

    (table,) = _extract(doc, tmp_path)

    assert table.caption == "Table 1: Results"
    assert table.image_path == "figures/page1_tab0.png"
    assert table.bbox[1] < 241 and table.bbox[3] > 319  # the whole table, top rule to bottom rule


def test_captioned_raster_figure_is_one_crop_not_a_raw_duplicate(tmp_path: Path) -> None:
    doc, page = new_pdf()
    page.insert_image(fitz.Rect(100, 100, 300, 220), stream=png_bytes())
    add_caption(page, 240, "Figure 1: A raster figure")

    figures = _extract(doc, tmp_path)

    assert [f.image_path for f in figures] == ["figures/page1_vec0.png"]
    assert figures[0].caption == "Figure 1: A raster figure"


def test_figure_made_of_several_images_is_one_crop(tmp_path: Path) -> None:
    """DeepSeek-V3 Figure 10: two plots plus two zoom insets under one
    caption used to come out as four cards with the same caption."""
    doc, page = new_pdf()
    for rect in [(90, 100, 270, 220), (180, 105, 255, 155), (280, 100, 460, 220), (370, 105, 445, 155)]:
        page.insert_image(fitz.Rect(*rect), stream=png_bytes())
    add_caption(page, 240, "Figure 10: Loss curves comparison between BF16 and FP8 training, EMA smoothed")

    (figure,) = _extract(doc, tmp_path)

    assert figure.image_path == "figures/page1_vec0.png"
    assert figure.bbox[0] < 91 and figure.bbox[2] > 459  # both plots
    assert list((tmp_path / "figures").iterdir()) == [tmp_path / "figures" / "page1_vec0.png"]


def test_side_by_side_panels_under_a_short_caption_are_one_crop(tmp_path: Path) -> None:
    """GLM-5 Figure 3: two screenshots 14pt apart under a caption just short
    of "wide" used to yield one panel as the figure and the other as a stray
    uncaptioned image."""
    doc, page = new_pdf()
    page.insert_image(fitz.Rect(100, 100, 280, 220), stream=png_bytes())
    page.insert_image(fitz.Rect(300, 100, 480, 220), stream=png_bytes(), keep_proportion=False)
    add_caption(page, 240, "Figure 3: Two panels under one caption, not wide", x=160)

    (figure,) = _extract(doc, tmp_path)

    assert figure.bbox[0] < 101 and figure.bbox[2] > 479


def test_drawing_running_off_the_page_does_not_hide_the_figure(tmp_path: Path) -> None:
    """GLM-5 Figure 11: one path ended at y=2402 on a 792pt page, inflating
    the figure past the size limit so it got no crop at all."""
    doc, page = new_pdf()
    draw_diagram(page, 100, 100)
    page.draw_line((150, 120), (150, 2400), color=(0, 0, 0))
    add_caption(page, 270, "Figure 11: Has a stray path")

    (figure,) = _extract(doc, tmp_path)

    assert figure.bbox[3] < 262


def test_icons_inside_a_drawn_diagram_do_not_suppress_or_fragment_it(tmp_path: Path) -> None:
    """DeepSeek-V3 Figures 6/7: small raster icons inside a vector diagram
    became junk figures and blocked the diagram's own crop."""
    doc, page = new_pdf()
    draw_diagram(page, 100, 100)
    for x in (130, 230):
        page.insert_image(fitz.Rect(x, 130, x + 20, 150), stream=png_bytes())
    add_caption(page, 270, "Figure 6: A diagram with icons")

    (figure,) = _extract(doc, tmp_path)

    assert figure.image_path == "figures/page1_vec0.png"
    assert figure.caption == "Figure 6: A diagram with icons"


def test_uncaptioned_image_kept_only_when_figure_sized(tmp_path: Path) -> None:
    doc, page = new_pdf()
    page.insert_image(fitz.Rect(100, 100, 300, 220), stream=png_bytes())  # figure-sized
    page.insert_image(fitz.Rect(100, 400, 280, 407), stream=png_bytes())  # a colorbar strip

    figures = _extract(doc, tmp_path)

    assert [f.image_path for f in figures] == ["figures/page1_fig0.png"]
    assert figures[0].caption is None


def test_white_background_shape_does_not_drag_heading_into_crop(tmp_path: Path) -> None:
    """DeepSeek-V3 Figure 10 sat on an invisible white rectangle reaching up
    over the section heading, which ended up in the crop."""
    doc, page = new_pdf()
    add_caption(page, 90, "B. Ablation Studies")
    page.draw_rect(fitz.Rect(72, 70, 540, 330), color=None, fill=(1, 1, 1))
    draw_diagram(page, 100, 150)
    add_caption(page, 330, "Figure 1: On a white background")

    (figure,) = _extract(doc, tmp_path)

    assert figure.bbox[1] > 100


def test_prose_starting_with_table_n_is_not_a_caption(tmp_path: Path) -> None:
    doc, page = new_pdf()
    for i in range(3):
        page.draw_line((72, 240 + i * 20), (400, 240 + i * 20), color=(0, 0, 0), width=0.5)
    add_caption(page, 300, "Table 6 presents the evaluation results")

    assert _extract(doc, tmp_path) == []


def test_page_border_and_full_width_rules_are_not_a_figure(tmp_path: Path) -> None:
    doc, page = new_pdf()
    page.draw_rect(fitz.Rect(20, 20, 592, 772), color=(0, 0, 0))  # page border
    page.draw_line((30, 60), (582, 60), color=(0, 0, 0))  # header rule
    page.draw_line((30, 330), (582, 330), color=(0, 0, 0))  # rules above caption
    page.draw_line((30, 336), (582, 336), color=(0, 0, 0))
    add_caption(page, 350, "Figure 1: Only furniture above me")

    assert _extract(doc, tmp_path) == []


def test_figure_does_not_swallow_body_text_above(tmp_path: Path) -> None:
    doc, page = new_pdf()
    add_body(page, 60, 200)
    draw_diagram(page, 100, 230)
    add_caption(page, 410, "Figure 1: Overview")

    (figure,) = _extract(doc, tmp_path)

    assert figure.bbox[1] > 195


def test_caption_above_figure_is_supported(tmp_path: Path) -> None:
    doc, page = new_pdf()
    add_caption(page, 100, "Figure 2: Caption sits over the drawing")
    draw_diagram(page, 100, 115)
    add_body(page, 300, 420)

    (figure,) = _extract(doc, tmp_path)

    assert figure.bbox[1] > 100 and figure.bbox[3] < 300


def test_per_page_cap_is_enforced(tmp_path: Path) -> None:
    doc, page = new_pdf(612, 2600)
    for i in range(MAX_FIGURES_PER_PAGE + 3):
        draw_diagram(page, 100, 20 + i * 170)
        add_caption(page, 20 + i * 170 + 160, f"Figure {i + 1}: Diagram number {i + 1}")

    figures = _extract(doc, tmp_path)

    assert len(figures) == MAX_FIGURES_PER_PAGE
    assert len(list((tmp_path / "figures").glob("page1_vec*.png"))) == MAX_FIGURES_PER_PAGE


def test_remaining_paper_budget_limits_a_page(tmp_path: Path) -> None:
    doc, page = new_pdf()
    draw_diagram(page, 100, 100)
    add_caption(page, 260, "Figure 1: One")

    assert _extract(doc, tmp_path, max_figures=0) == []


def test_per_paper_cap_is_enforced(tmp_path: Path) -> None:
    doc = fitz.open()
    for _ in range(8):
        page = doc.new_page(width=612, height=1900)
        for i in range(10):
            draw_diagram(page, 100, 20 + i * 170)
            add_caption(page, 20 + i * 170 + 160, f"Figure {i + 1}: Diagram")
    pdf = tmp_path / "many.pdf"
    doc.save(str(pdf))
    doc.close()

    by_page = extract_document_figures(str(pdf), str(tmp_path / "out"))

    assert sum(len(v) for v in by_page.values()) == MAX_FIGURES_PER_PAPER
    assert len(list((tmp_path / "out" / "figures").glob("*.png"))) == MAX_FIGURES_PER_PAPER


def test_rendered_pixels_are_capped_on_huge_pages(tmp_path: Path) -> None:
    doc, page = new_pdf(6000, 4000)
    draw_diagram(page, 200, 200, w=5000, h=2500)
    add_caption(page, 2740, "Figure 1: A very large drawing")

    (figure,) = _extract(doc, tmp_path)

    with Image.open(tmp_path / figure.image_path) as img:
        assert max(img.size) <= 2400


def test_caption_scan_is_capped_per_page(tmp_path: Path, monkeypatch) -> None:
    """Security review: a page with far more "Figure N:" -shaped text blocks
    than any real paper has (no matching drawing for any of them, so the
    result-count early-break in ``extract_vector_figures`` never fires) must
    not cost unbounded work -- the caption scan itself has to be capped."""
    doc, page = new_pdf(612, 20_000)
    fake_caption_count = _MAX_CAPTIONS_PER_PAGE * 5
    blocks = [
        (72.0, float(i * 20), 400.0, float(i * 20 + 12), f"Figure {i}: nothing is drawn near this one", i, 0)
        for i in range(fake_caption_count)
    ]

    seen: list[object] = []
    real_find_region = vector_figures._find_region

    def _counting_find_region(caption, texts, drawings, page_box):
        seen.append(caption)
        return real_find_region(caption, texts, drawings, page_box)

    monkeypatch.setattr(vector_figures, "_find_region", _counting_find_region)

    result = extract_vector_figures(page, 1, tmp_path, blocks, [], max_figures=999)

    assert result == []  # nothing was ever drawn, so nothing is extracted
    assert len(seen) == _MAX_CAPTIONS_PER_PAGE  # the scan itself is bounded, not just the output


def test_hostile_caption_text_never_reaches_the_filename(tmp_path: Path) -> None:
    doc, page = new_pdf()
    draw_diagram(page, 100, 100)
    add_caption(page, 260, "Figure 1: ../../evil\\name.png")

    (figure,) = _extract(doc, tmp_path)

    assert figure.image_path == "figures/page1_vec0.png"
    assert [p.name for p in (tmp_path / "figures").iterdir()] == ["page1_vec0.png"]
