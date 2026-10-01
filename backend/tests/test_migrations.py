"""``alembic upgrade head`` on a fresh database, then ``alembic check`` -- the
migrations and the ORM models must describe the same schema (no drift)."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import TEST_DATABASE_URL

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=180
    )


@pytest.fixture
async def fresh_database_url() -> str:
    name = f"papertrail_mig_{uuid.uuid4().hex[:10]}"
    admin = create_async_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(TEST_DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def test_upgrade_head_on_fresh_database_has_no_model_drift(fresh_database_url: str) -> None:
    upgrade = _alembic(fresh_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    heads = _alembic(fresh_database_url, "heads")
    assert "0014" in heads.stdout

    check = _alembic(fresh_database_url, "check")
    assert check.returncode == 0, check.stdout + check.stderr

    engine = create_async_engine(fresh_database_url, poolclass=NullPool)
    async with engine.connect() as conn:
        tables = {row[0] for row in await conn.execute(text("select tablename from pg_tables where schemaname='public'"))}
        column = await conn.scalar(
            text("select data_type from information_schema.columns where table_name='generated_sections' and column_name='data'")
        )
    await engine.dispose()
    assert {"stories", "figures"} <= tables
    assert column == "jsonb"


async def test_downgrade_then_upgrade_round_trips(fresh_database_url: str) -> None:
    assert _alembic(fresh_database_url, "upgrade", "head").returncode == 0
    down = _alembic(fresh_database_url, "downgrade", "0013")
    assert down.returncode == 0, down.stderr
    up = _alembic(fresh_database_url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
