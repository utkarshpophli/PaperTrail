"""Local mode: no login, every request acts as one fixed local user."""

from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.dependencies import LOCAL_USER_EMAIL, LOCAL_USER_ID
from app.core.config import get_settings
from app.models.user import User


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async with async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)() as session:
        yield session


@pytest.fixture
def local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "local_mode", True)


async def test_requests_work_without_a_token(client: AsyncClient, local_mode: None) -> None:
    response = await client.get("/papers")

    assert response.status_code == 200
    assert response.json() == []


async def test_local_user_is_created_once_and_reused(
    client: AsyncClient, db_session: AsyncSession, local_mode: None
) -> None:
    for _ in range(3):
        assert (await client.get("/papers")).status_code == 200

    count = await db_session.scalar(select(func.count()).select_from(User).where(User.id == LOCAL_USER_ID))
    assert count == 1
    user = await db_session.get(User, LOCAL_USER_ID)
    assert user is not None and user.email == LOCAL_USER_EMAIL


async def test_local_user_cannot_be_logged_into(client: AsyncClient, local_mode: None) -> None:
    await client.get("/papers")  # provisions the user

    response = await client.post("/auth/login", json={"email": LOCAL_USER_EMAIL, "password": "anything-at-all"})

    # 422 (the reserved .local domain fails email validation) or 401: never a token.
    assert response.status_code in (401, 422)
    assert "access_token" not in response.text


async def test_ownership_still_scopes_queries(client: AsyncClient, db_session: AsyncSession, local_mode: None) -> None:
    from app.models.paper import Paper, ParseStatus

    other = User(email="someone-else@example.com", hashed_password="x")
    db_session.add(other)
    await db_session.flush()
    foreign = Paper(
        user_id=other.id, title="Not mine", authors=[], source_file_path="/x", parse_status=ParseStatus.parsed
    )
    db_session.add(foreign)
    await db_session.commit()

    assert (await client.get("/papers")).json() == []
    assert (await client.get(f"/papers/{foreign.id}")).status_code == 404


async def test_without_local_mode_a_token_is_still_required(client: AsyncClient) -> None:
    response = await client.get("/papers")

    assert response.status_code == 401


async def test_non_loopback_client_is_rejected_in_local_mode(local_mode: None) -> None:
    """With no login, a request from another machine (API started with
    --host 0.0.0.0) must be refused, not served as the local user."""
    from httpx import ASGITransport

    from app.main import app

    remote = ASGITransport(app=app, client=("192.168.1.50", 5555))
    async with AsyncClient(transport=remote, base_url="http://test") as client:
        response = await client.get("/papers")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "local_mode_loopback_only"
