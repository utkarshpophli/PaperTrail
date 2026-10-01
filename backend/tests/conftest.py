"""Pytest fixtures for the auth test suite.

Tests run against a REAL Postgres database (TESTING.md: "not mocks of your
own persistence layer") — point ``TEST_DATABASE_URL`` at a disposable test
database before running pytest. See backend/README section in the task
report for the exact command.

Required env vars (DATABASE_URL, JWT_SECRET_KEY) are set here, before any
``app`` module is imported, because ``Settings`` is read at import time in
several modules.
"""

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, Generator

# Always assigned, never setdefault: the suite drops and recreates every
# table, so a DATABASE_URL already exported for the dev server must never be
# what it runs against.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://papertrail:papertrail@localhost:5432/papertrail_test",
)
if "test" not in os.environ["DATABASE_URL"].rsplit("/", 1)[-1].lower():
    raise RuntimeError(
        "Refusing to run: the test database name must contain 'test' (the suite drops every table). "
        "Point TEST_DATABASE_URL at a disposable database."
    )
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-not-for-production")
# The existing suite exercises real bearer-token auth; local mode has its own tests.
os.environ["LOCAL_MODE"] = "false"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import citation_edge as _citation_edge  # noqa: E402,F401  register model on Base.metadata
from app.models import claim as _claim  # noqa: E402,F401  register model on Base.metadata
from app.models import code_link as _code_link  # noqa: E402,F401  register model on Base.metadata
from app.models import collection as _collection  # noqa: E402,F401  register model on Base.metadata
from app.models import evidence as _evidence  # noqa: E402,F401  register model on Base.metadata
from app.models import generated_section as _generated_section  # noqa: E402,F401  register model on Base.metadata
from app.models import figure as _figure  # noqa: E402,F401  register model on Base.metadata
from app.models import glossary_term as _glossary_term  # noqa: E402,F401  register model on Base.metadata
from app.models import learning_derivation as _learning_derivation  # noqa: E402,F401  register model on Base.metadata
from app.models import learning_interactive as _learning_interactive  # noqa: E402,F401  register model
from app.models import learning_quiz_question as _learning_quiz_question  # noqa: E402,F401  register model
from app.models import metric as _metric  # noqa: E402,F401  register model on Base.metadata
from app.models import page as _page  # noqa: E402,F401  register model on Base.metadata
from app.models import paper as _paper  # noqa: E402,F401  register model on Base.metadata
from app.models import profile as _profile  # noqa: E402,F401  register model on Base.metadata
from app.models import repository as _repository  # noqa: E402,F401  register model on Base.metadata
from app.models import roadmap as _roadmap  # noqa: E402,F401  register model on Base.metadata
from app.models import source_reference as _source_reference  # noqa: E402,F401  register model on Base.metadata
from app.models import story as _story  # noqa: E402,F401  register model on Base.metadata
from app.models import topic_landscape as _topic_landscape  # noqa: E402,F401  register model on Base.metadata
from app.models import user as _user  # noqa: E402,F401  register model on Base.metadata
from app.providers.rate_limit import reset_for_tests as _reset_provider_rate_limits  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    # The default storage_dir is the cwd-relative "./storage" -- the dev
    # server's real paper directory when pytest runs from backend/. Tests used
    # to rmtree it on teardown, which wiped every dev paper's PDF and figures.
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path_factory.mktemp("storage")))


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    limiter.reset()
    _reset_provider_rate_limits()


@pytest.fixture
def caplog(caplog: pytest.LogCaptureFixture) -> Generator[pytest.LogCaptureFixture, None, None]:
    """Makes ``caplog`` actually see application logs.

    ``app.core.logging.get_logger`` sets ``propagate = False``, so pytest's
    stock ``caplog`` (a root-logger handler) records nothing from any
    ``app.*`` logger -- every "never logs the API key" assertion written
    against it passed vacuously. Propagation is switched on for the duration
    of the test only.
    """
    app_loggers = [
        logger
        for name, logger in logging.root.manager.loggerDict.items()
        if name.startswith("app.") and isinstance(logger, logging.Logger)
    ]
    original = [(logger, logger.propagate) for logger in app_loggers]
    for logger in app_loggers:
        logger.propagate = True
    try:
        yield caplog
    finally:
        for logger, propagate in original:
            logger.propagate = propagate


@pytest.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    # ponytail: fresh engine per test (NullPool, no connection reuse) rather
    # than one module-level engine — asyncpg connections are bound to the
    # event loop they were created on, and pytest-asyncio gives each test
    # function its own loop, so a shared engine corrupts across tests.
    test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)

    # Every test recreates the full schema against one shared physical DB —
    # cheap when it was a handful of tables, but by Phase 4b-i this DDL churn
    # (drop_all/create_all x 170+ tests) is racy enough under Docker-Desktop-
    # on-Windows connection churn to intermittently hit transient deadlocks/
    # connection resets even on already-passing, unrelated tests (observed:
    # test_auth.py failures with no code path anywhere near this phase).
    # Retrying the DDL step a few times absorbs that transient contention
    # without masking a real migration/model bug (a genuinely broken schema
    # fails identically on every retry, so this can't hide an actual defect).
    last_error: DBAPIError | None = None
    for attempt in range(3):
        try:
            async with test_engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
            break
        except DBAPIError as exc:
            last_error = exc
            await asyncio.sleep(0.5 * (attempt + 1))
    else:
        raise last_error  # type: ignore[misc]

    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def client(db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    # BackgroundTasks (e.g. app.papers.service.run_parsing) open their own
    # session via the module-level AsyncSessionLocal rather than the get_db
    # dependency, since the request-scoped session is closed by the time
    # they run. That module-level engine is a long-lived singleton bound to
    # whatever event loop existed when app.db.session was first imported —
    # fine in production (one event loop for the app's lifetime), but wrong
    # across pytest tests, each with its own fresh event loop (same reason
    # db_engine above is per-test with NullPool). Point background tasks at
    # this test's own per-loop engine instead.
    monkeypatch.setattr("app.papers.service.AsyncSessionLocal", session_factory)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
