"""Fixtures shared by the Evidence Engine test suite. Reuses the top-level
``db_engine`` fixture (real Postgres, per TESTING.md: "test evidence merging
... against a real (test) database ... not mocks of your own persistence
layer") rather than building a second DB fixture.
"""

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.page import Page
from app.models.paper import Paper, ParseStatus
from app.models.user import User

_FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


@pytest.fixture
def s2orc_pdf_path() -> str:
    return str(_FIXTURES_DIR / "s2orc_1911.02782v3.pdf")


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session


async def make_parsed_paper(db: AsyncSession, pages: dict[int, str]) -> Paper:
    """Inserts a User + Paper(parse_status=parsed) + one Page row per
    ``{page_number: text}`` entry, and returns the persisted Paper."""
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.commit()

    paper = Paper(
        id=uuid.uuid4(),
        user_id=user.id,
        title="Test Paper",
        authors=["A. Author"],
        source_file_path="/tmp/test.pdf",
        parse_status=ParseStatus.parsed,
    )
    db.add(paper)
    # Committed separately from the Page rows below -- like the real
    # ingestion pipeline (app.papers.service: create_paper_from_upload
    # commits the Paper, run_parsing adds Pages in a later transaction). The
    # ORM's flush-order dependency sort is driven by relationship() objects,
    # and Paper<->Page has none (plain FK column only) -- inserting both in
    # one flush isn't guaranteed to order Paper's INSERT before Page's.
    await db.commit()

    for number, text in pages.items():
        db.add(Page(paper_id=paper.id, page_number=number, text=text))
    await db.commit()
    return paper
