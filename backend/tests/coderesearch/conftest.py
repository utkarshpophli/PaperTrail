"""Fixtures for claim-to-code linking tests: real Postgres (TESTING.md: not
mocks of our own persistence layer), seeded user/paper/claim/repository."""

import logging
import uuid
from collections.abc import Generator
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.claim import Claim, ClaimKind
from app.models.paper import Paper
from app.models.repository import Repository
from app.models.source_reference import SourceReference
from app.models.user import User


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def log_messages() -> Generator[list[str], None, None]:
    """Captures every message the code-research loggers emit. ``caplog`` can't
    be used: ``app.core.logging.get_logger`` sets ``propagate = False``, so
    caplog's root handler never sees these records."""
    handler = _ListHandler()
    names = ("app.coderesearch.router", "app.coderesearch.code_linking", "app.coderesearch.github_client")
    loggers = [logging.getLogger(name) for name in names]
    for logger in loggers:
        logger.addHandler(handler)
    yield handler.messages
    for logger in loggers:
        logger.removeHandler(handler)


@dataclass
class Seed:
    user: User
    paper: Paper
    repository: Repository
    method_claim: Claim
    result_claim: Claim
    background_claim: Claim


async def add_paper(db: AsyncSession, user: User, title: str = "Paper") -> Paper:
    paper = Paper(id=uuid.uuid4(), user_id=user.id, title=title, authors=["A"], source_file_path="/tmp/x.pdf")
    db.add(paper)
    await db.commit()
    return paper


async def add_claim(db: AsyncSession, paper: Paper, kind: ClaimKind, statement: str) -> Claim:
    claim = Claim(id=uuid.uuid4(), paper_id=paper.id, statement=statement, kind=kind)
    db.add(claim)
    await db.commit()
    db.add(SourceReference(claim_id=claim.id, page=1, excerpt=f"source excerpt for {statement}"))
    await db.commit()
    await db.refresh(claim)
    return claim


async def add_repository(db: AsyncSession, paper: Paper, user: User) -> Repository:
    repository = Repository(
        paper_id=paper.id,
        user_id=user.id,
        url="https://github.com/o/r",
        owner="o",
        name="r",
        source="user_linked",
    )
    db.add(repository)
    await db.commit()
    return repository


async def add_user(db: AsyncSession) -> User:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.commit()
    return user


@pytest.fixture
async def seed(db_session: AsyncSession) -> Seed:
    user = await add_user(db_session)
    paper = await add_paper(db_session, user)
    return Seed(
        user=user,
        paper=paper,
        repository=await add_repository(db_session, paper, user),
        method_claim=await add_claim(db_session, paper, ClaimKind.method, "Uses scaled dot-product attention."),
        result_claim=await add_claim(db_session, paper, ClaimKind.reported_result, "Reaches 28.4 BLEU."),
        background_claim=await add_claim(db_session, paper, ClaimKind.background, "Attention is old."),
    )
