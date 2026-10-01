"""Fixture paths for the Document Pipeline test suite. These tests parse
real files with plain functions — no DB, no app, no auth fixtures needed
(unlike backend/tests/conftest.py, which this directory still inherits but
does not exercise)."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


@pytest.fixture
def s2orc_pdf_path() -> str:
    return str(FIXTURES_DIR / "s2orc_1911.02782v3.pdf")


@pytest.fixture
def synthetic_scanned_pdf_path() -> str:
    return str(FIXTURES_DIR / "synthetic_scanned.pdf")
