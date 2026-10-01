"""Contract tests for ``POST /discover/landscape/{id}/promote`` -- auth,
ownership, and the request/response shape. ``app.discovery.service
.promote_landscape``'s split logic itself is covered by
``test_promote_service.py``.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.paper import Paper, ParseStatus
from app.models.topic_landscape import TopicLandscape
from app.models.user import User

PASSWORD = "correct-horse-battery"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    login_response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_response.status_code == 200, login_response.text
    return login_response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _get_user_by_email(db_engine: AsyncEngine, email: str) -> User:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as db:
        user = (await db.scalars(select(User).where(User.email == email))).first()
        assert user is not None
        return user


async def _seed_landscape(db_engine: AsyncEngine, user_id: uuid.UUID, papers: list[dict]) -> uuid.UUID:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as db:
        landscape = TopicLandscape(user_id=user_id, topic="t", overview="o", papers=papers, clusters=[])
        db.add(landscape)
        await db.commit()
        await db.refresh(landscape)
        return landscape.id


def _landscape_paper(arxiv_id: str) -> dict:
    return {
        "arxiv_id": arxiv_id,
        "title": f"Paper {arxiv_id}",
        "authors": [],
        "year": 2021,
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
        "abstract": "abstract",
        "relevance_score": 0.5,
        "cluster_id": None,
        "extraction": None,
    }


async def test_promote_requires_auth(client: AsyncClient) -> None:
    response = await client.post(f"/discover/landscape/{uuid.uuid4()}/promote", json={"collection_name": "x"})
    assert response.status_code == 401


async def test_promote_not_owned_landscape_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "promote-notfound@example.com")

    response = await client.post(
        f"/discover/landscape/{uuid.uuid4()}/promote",
        headers=_auth_headers(token),
        json={"collection_name": "x"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "topic_landscape_not_found"


async def test_promote_rejects_missing_target(client: AsyncClient, db_engine: AsyncEngine) -> None:
    email = "promote-missing-target@example.com"
    token = await _register_and_login(client, email)
    user = await _get_user_by_email(db_engine, email)
    landscape_id = await _seed_landscape(db_engine, user.id, [])

    response = await client.post(
        f"/discover/landscape/{landscape_id}/promote", headers=_auth_headers(token), json={}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_promote_target"


async def test_promote_is_rate_limited_per_user(client: AsyncClient, db_engine: AsyncEngine) -> None:
    email = "promote-ratelimited@example.com"
    token = await _register_and_login(client, email)
    user = await _get_user_by_email(db_engine, email)
    landscape_id = await _seed_landscape(db_engine, user.id, [])

    responses = [
        await client.post(
            f"/discover/landscape/{landscape_id}/promote",
            headers=_auth_headers(token),
            json={"collection_name": f"list {i}"},
        )
        for i in range(11)
    ]

    assert responses[-1].status_code == 429


async def test_promote_happy_path_splits_added_and_skipped(client: AsyncClient, db_engine: AsyncEngine) -> None:
    email = "promote-happy@example.com"
    token = await _register_and_login(client, email)
    user = await _get_user_by_email(db_engine, email)

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as db:
        owned_paper = Paper(
            user_id=user.id,
            title="Owned",
            authors=[],
            source_file_path="/tmp/a.pdf",
            parse_status=ParseStatus.parsed,
            arxiv_id="2001.00099",
        )
        db.add(owned_paper)
        await db.commit()

    landscape_id = await _seed_landscape(
        db_engine, user.id, [_landscape_paper("2001.00099"), _landscape_paper("2001.00098")]
    )

    response = await client.post(
        f"/discover/landscape/{landscape_id}/promote",
        headers=_auth_headers(token),
        json={"collection_name": "Promoted"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["added"] == ["2001.00099"]
    assert body["skipped_not_ingested"] == ["2001.00098"]
    assert body["collection_id"]
