"""Fixtures shared by the Discovery test suite. Reuses the top-level
``db_engine`` fixture (real Postgres) rather than building a second DB
fixture, same pattern as ``tests/evidence/conftest.py``.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

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
