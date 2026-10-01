"""Contract tests for ``POST /graph/papers/{id}/citations/refresh``: auth,
ownership (404-not-403, before any external call), rate limiting (5/hour),
API key never logged, OpenAlex failure surfaced as a typed 502, and an
end-to-end run with OpenAlex + provider mocked at their boundaries.
"""

import logging
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.graph import citations as citations_module
from app.graph.exceptions import OpenAlexUnavailableError
from app.graph.openalex_client import OpenAlexWork
from app.models.paper import Paper
from app.models.user import User
from tests.evidence.fake_provider import FakeProvider
from tests.graph.conftest import make_analyzed_paper

PASSWORD = "correct-horse-battery"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    login_response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_response.status_code == 200, login_response.text
    return login_response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _url(paper_id: uuid.UUID) -> str:
    return f"/graph/papers/{paper_id}/citations/refresh"


def _sessions(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


async def _owned_paper(client: AsyncClient, db_engine: AsyncEngine, email: str, title: str = "A") -> tuple[str, Paper]:
    """Registers ``email`` and seeds one analyzed paper owned by that user."""
    token = await _register_and_login(client, email)
    async with _sessions(db_engine)() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        paper = await make_analyzed_paper(session, user.id, title, f"thesis {title}", "summary")
    return token, paper


def _mock_no_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(*args: object, **kwargs: object) -> list[object]:
        return []

    monkeypatch.setattr("app.graph.citations.fetch_citation_edges_for_paper", _fake)


async def test_refresh_requires_auth(client: AsyncClient) -> None:
    response = await client.post(_url(uuid.uuid4()), json={"provider_id": "google"})
    assert response.status_code == 401


async def test_refresh_not_owned_paper_is_404_before_any_external_call(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _must_not_run(*args: object, **kwargs: object) -> list[object]:
        raise AssertionError("OpenAlex/provider work must not start for a non-owned paper")

    monkeypatch.setattr("app.graph.citations.fetch_citation_edges_for_paper", _must_not_run)
    token = await _register_and_login(client, "refresh-notowned@example.com")

    response = await client.post(_url(uuid.uuid4()), headers=_auth(token), json={"provider_id": "google", "api_key": "sk-x", "model": "m"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_refresh_other_users_paper_is_404(client: AsyncClient, db_engine: AsyncEngine) -> None:
    _, paper = await _owned_paper(client, db_engine, "refresh-owner@example.com")
    intruder_token = await _register_and_login(client, "refresh-intruder@example.com")

    response = await client.post(
        _url(paper.id), headers=_auth(intruder_token), json={"provider_id": "google", "api_key": "sk-x", "model": "m"}
    )

    assert response.status_code == 404


async def test_refresh_unknown_provider_is_404(client: AsyncClient, db_engine: AsyncEngine) -> None:
    token, paper = await _owned_paper(client, db_engine, "refresh-badprovider@example.com")

    response = await client.post(_url(paper.id), headers=_auth(token), json={"provider_id": "not-a-real-provider", "model": "m"})

    assert response.status_code == 404


async def test_refresh_end_to_end_returns_and_persists_classified_edge(
    client: AsyncClient, db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, paper_a = await _owned_paper(client, db_engine, "refresh-happy@example.com", "A")
    async with _sessions(db_engine)() as session:
        paper_b = await make_analyzed_paper(session, paper_a.user_id, "B", "thesis B", "summary")

    works = {"A": OpenAlexWork("W_A", ["W_B"]), "B": OpenAlexWork("W_B", [])}

    async def _fake_resolve(*, doi: str | None = None, title: str | None = None) -> OpenAlexWork | None:
        return works.get(title or "")

    monkeypatch.setattr("app.graph.citations.resolve_openalex_work", _fake_resolve)
    classification = citations_module._RelationClassification(relation="extends", confidence=0.85, reasoning="builds on it")
    fake = FakeProvider({citations_module._RelationClassification: classification})
    monkeypatch.setattr("app.graph.router.build_provider", lambda *args, **kwargs: fake)

    response = await client.post(_url(paper_a.id), headers=_auth(token), json={"provider_id": "google", "api_key": "sk-x", "model": "m"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert set(body[0].keys()) == {
        "id", "from_paper_id", "to_paper_id", "relation", "confidence", "openalex_work_id", "fetched_at"
    }
    assert body[0]["from_paper_id"] == str(paper_a.id)
    assert body[0]["to_paper_id"] == str(paper_b.id)
    assert body[0]["relation"] == "extends"
    assert body[0]["confidence"] == 0.85
    assert body[0]["openalex_work_id"] == "W_B"

    async with _sessions(db_engine)() as session:
        rows = await citations_module.get_cached_citation_edges(session, paper_a.user_id)
    assert [(r.relation, r.confidence) for r in rows] == [("extends", 0.85)]


async def test_refresh_no_citations_found_returns_empty_list(
    client: AsyncClient, db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, paper = await _owned_paper(client, db_engine, "refresh-empty@example.com")
    _mock_no_citations(monkeypatch)

    response = await client.post(_url(paper.id), headers=_auth(token), json={"provider_id": "google", "api_key": "sk-x", "model": "m"})

    assert response.status_code == 200
    assert response.json() == []


async def test_refresh_is_rate_limited_to_5_per_hour(
    client: AsyncClient, db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, paper = await _owned_paper(client, db_engine, "refresh-ratelimit@example.com")
    _mock_no_citations(monkeypatch)

    responses = [
        await client.post(_url(paper.id), headers=_auth(token), json={"provider_id": "google", "api_key": "sk-x", "model": "m"})
        for _ in range(6)
    ]

    assert [r.status_code for r in responses[:5]] == [200] * 5
    assert responses[5].status_code == 429


async def test_refresh_never_logs_api_key(
    client: AsyncClient, db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    token, paper = await _owned_paper(client, db_engine, "refresh-nolog@example.com")
    _mock_no_citations(monkeypatch)
    secret_key = "sk-super-secret-refresh-13579"

    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            _url(paper.id), headers=_auth(token), json={"provider_id": "google", "api_key": secret_key, "model": "m"}
        )

    assert response.status_code == 200
    for record in caplog.records:
        assert secret_key not in record.getMessage()


async def test_refresh_openalex_unavailable_surfaces_as_502(
    client: AsyncClient, db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, paper = await _owned_paper(client, db_engine, "refresh-502@example.com")

    async def _boom(**kwargs: object) -> None:
        raise OpenAlexUnavailableError("down")

    monkeypatch.setattr("app.graph.citations.resolve_openalex_work", _boom)

    response = await client.post(_url(paper.id), headers=_auth(token), json={"provider_id": "google", "api_key": "sk-x", "model": "m"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "openalex_unavailable"
