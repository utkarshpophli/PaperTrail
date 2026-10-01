"""Figure extraction tests against the golden fixture set."""

from pathlib import Path

from app.documents.parser import parse_pdf


def test_extracts_at_least_one_figure_with_page_and_caption(s2orc_pdf_path: str, tmp_path: Path) -> None:
    doc = parse_pdf(s2orc_pdf_path, str(tmp_path))

    all_figures = [figure for page in doc.pages for figure in page.figures]
    assert len(all_figures) >= 1

    captioned = [figure for figure in all_figures if figure.caption]
    assert len(captioned) >= 1
    assert captioned[0].page >= 1


def test_figure_image_file_actually_written_to_output_dir(s2orc_pdf_path: str, tmp_path: Path) -> None:
    doc = parse_pdf(s2orc_pdf_path, str(tmp_path))

    all_figures = [figure for page in doc.pages for figure in page.figures]
    assert all_figures, "fixture is expected to contain embedded figures"

    for figure in all_figures:
        assert (tmp_path / figure.image_path).exists()


def test_synthetic_fixture_figure_gets_correct_page_and_caption(
    synthetic_scanned_pdf_path: str, tmp_path: Path
) -> None:
    doc = parse_pdf(synthetic_scanned_pdf_path, str(tmp_path))

    page1_figures = doc.pages[0].figures
    assert len(page1_figures) == 1
    assert page1_figures[0].page == 1
    assert page1_figures[0].caption is not None
    assert "figure 1" in page1_figures[0].caption.lower()


def test_full_page_scan_image_is_not_treated_as_a_figure(synthetic_scanned_pdf_path: str, tmp_path: Path) -> None:
    doc = parse_pdf(synthetic_scanned_pdf_path, str(tmp_path))

    scanned_page = doc.pages[1]
    assert scanned_page.figures == []
