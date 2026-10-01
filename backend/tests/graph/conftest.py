"""Fixtures shared by the Literature Graph test suite. Reuses the top-level
``db_engine`` fixture (real Postgres), same pattern as
``tests/discovery/conftest.py``.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.evidence import Evidence
from app.models.paper import Paper, ParseStatus
from app.models.user import User


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session


async def make_user(db: AsyncSession) -> User:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.commit()
    return user


async def make_analyzed_paper(db: AsyncSession, user_id: uuid.UUID, title: str, thesis: str, plain_summary: str) -> Paper:
    """A Paper + its completed Evidence row -- the minimum shape
    ``app.graph.service`` requires for a paper to appear on the graph."""
    paper = Paper(
        user_id=user_id,
        title=title,
        authors=[],
        source_file_path="/tmp/test.pdf",
        parse_status=ParseStatus.parsed,
    )
    db.add(paper)
    await db.commit()

    db.add(Evidence(paper_id=paper.id, thesis=thesis, plain_summary=plain_summary, research_question="?"))
    await db.commit()
    await db.refresh(paper)
    return paper
