"""Tests against the golden fixture set (docs/TESTING.md) — real parsing,
no mocks of PyMuPDF/pytesseract, per TESTING.md's "not mocks of the thing
under test" rule.
"""

import shutil
from pathlib import Path

import pytest

from app.documents.exceptions import DocumentUnreadableError
from app.documents.parser import parse_pdf

requires_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="Tesseract OCR binary not found on PATH — see docs/DEVELOPMENT.md prerequisites",
)


def test_parses_multi_column_fixture_extracts_nonempty_text(s2orc_pdf_path: str, tmp_path: Path) -> None:
    doc = parse_pdf(s2orc_pdf_path, str(tmp_path))

    assert len(doc.pages) > 1
    assert doc.metadata["unparsed_pages"] == []
    # every page of a born-digital paper should have real extracted text
    assert all(len(page.text.strip()) > 0 for page in doc.pages)
    assert "S2ORC" in doc.pages[0].text


def test_page_numbers_are_sequential_and_never_dropped(s2orc_pdf_path: str, tmp_path: Path) -> None:
    doc = parse_pdf(s2orc_pdf_path, str(tmp_path))

    assert [page.number for page in doc.pages] == list(range(1, len(doc.pages) + 1))


@requires_tesseract
def test_ocr_fallback_recovers_text_from_scanned_page(synthetic_scanned_pdf_path: str, tmp_path: Path) -> None:
    doc = parse_pdf(synthetic_scanned_pdf_path, str(tmp_path))

    assert len(doc.pages) == 2
    normal_page, scanned_page = doc.pages

    # page 1 has a real text layer — no OCR needed
    assert "real text layer" in normal_page.text

    # page 2 has no text layer at all; only OCR can recover this sentence
    assert "rendered image" in scanned_page.text.lower() or "fall back to ocr" in scanned_page.text.lower()
    assert doc.metadata["unparsed_pages"] == []


def test_embedded_nul_byte_is_stripped_from_extracted_text(
    s2orc_pdf_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Postgres rejects ``\\x00`` in a text column outright, regardless of
    encoding -- confirmed live against arXiv:2412.19437, where PyMuPDF's
    text extraction embeds a NUL byte for some font/ligature. Reaching the
    DB insert unsanitized silently failed the whole parse (see
    tests/test_papers.py's persistence-layer regression test for the other
    half of this fix)."""
    import fitz

    real_get_text = fitz.Page.get_text

    def poisoned_get_text(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = real_get_text(self, *args, **kwargs)
        if self.number == 0 and not args and not kwargs:  # only the plain-text call parse_pdf itself makes
            return result + "\x00"
        return result

    monkeypatch.setattr(fitz.Page, "get_text", poisoned_get_text)

    doc = parse_pdf(s2orc_pdf_path, str(tmp_path))

    assert "\x00" not in doc.pages[0].text
    assert doc.pages[0].text.strip() != ""  # the real text survived, not just the NUL byte


def test_unopenable_file_raises_typed_error(tmp_path: Path) -> None:
    bad_file = tmp_path / "not_a_pdf.pdf"
    bad_file.write_bytes(b"this is not a pdf")

    with pytest.raises(DocumentUnreadableError):
        parse_pdf(str(bad_file), str(tmp_path))


def test_page_that_fails_gets_empty_text_not_dropped(
    s2orc_pdf_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per ARCHITECTURE.md's error-handling rule: a page that fails entirely
    is marked unparsed, not silently dropped from ``pages[]``."""
    import app.documents.parser as parser_module

    real_extract_figures = parser_module.extract_figures

    def flaky_extract_figures(doc, page, page_number, output_dir, *args):  # type: ignore[no-untyped-def]
        if page_number == 2:
            raise RuntimeError("simulated corrupt page content stream")
        return real_extract_figures(doc, page, page_number, output_dir, *args)

    monkeypatch.setattr(parser_module, "extract_figures", flaky_extract_figures)

    doc = parser_module.parse_pdf(s2orc_pdf_path, str(tmp_path))

    assert len(doc.pages) > 2  # page count is preserved, nothing dropped
    failed_page = next(page for page in doc.pages if page.number == 2)
    assert failed_page.text == ""
    assert failed_page.figures == []
    assert doc.metadata["unparsed_pages"] == [2]
    # every other page still parsed normally
    assert doc.pages[0].text.strip() != ""
