"""Contract tests for the ``/discover/*`` routes: auth, ownership, rate
limiting, SSE streaming, validation, and secret handling -- same pattern as
``tests/test_assistant.py``. ``app.discovery.service``'s pipeline/ranking
logic itself is covered by ``test_service_integration.py``/unit tests, not
re-verified here.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.discovery.exceptions import TopicLandscapeNotFoundError
from app.discovery.service import AnalysisEvent
from app.models.topic_landscape import TopicLandscape

PASSWORD = "correct-horse-battery"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    login_response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_response.status_code == 200, login_response.text
    return login_response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _landscape_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "topic": "diffusion models",
        "provider_id": "google",
        "api_key": "sk-test",
        "model": "m",
        "embed_model": "m",
    }
    body.update(overrides)
    return body


async def _events_done() -> AsyncIterator[AnalysisEvent]:
    yield AnalysisEvent(type="progress", stage="landscape", message="Configuring AI provider")
    yield AnalysisEvent(
        type="done",
        stage="landscape",
        data={
            "id": str(uuid.uuid4()),
            "topic": "diffusion models",
            "overview": "An overview.",
            "papers": [],
            "clusters": [],
            "created_at": "2024-01-01T00:00:00Z",
        },
    )


def _mock_run_landscape_search(monkeypatch: pytest.MonkeyPatch, events_factory: object) -> None:
    monkeypatch.setattr("app.discovery.service.run_landscape_search", lambda **kwargs: events_factory())


def _sample_landscape(user_id: uuid.UUID) -> TopicLandscape:
    return TopicLandscape(
        id=uuid.uuid4(),
        user_id=user_id,
        topic="attention",
        overview="An overview of the landscape.",
        papers=[
            {
                "arxiv_id": "2001.00001",
                "title": "Paper A",
                "authors": ["Alice"],
                "year": 2021,
                "pdf_url": "https://arxiv.org/pdf/2001.00001",
                "abstract": "abstract A",
                "relevance_score": 0.9,
                "cluster_id": "c1",
                "extraction": None,
            },
            {
                "arxiv_id": "2001.00002",
                "title": "Paper B",
                "authors": ["Bob"],
                "year": 2022,
                "pdf_url": "https://arxiv.org/pdf/2001.00002",
                "abstract": "abstract B",
                "relevance_score": 0.5,
                "cluster_id": "c1",
                "extraction": None,
            },
        ],
        clusters=[{"id": "c1", "label": "Cluster 1", "description": "desc", "paper_ids": ["2001.00001", "2001.00002"]}],
        created_at=datetime.now(timezone.utc),
    )


# ---- POST /discover/landscape ---------------------------------------------


async def test_create_landscape_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/discover/landscape", json=_landscape_body())
    assert response.status_code == 401


async def test_create_landscape_rejects_empty_topic(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_run_landscape_search(monkeypatch, _events_done)
    token = await _register_and_login(client, "landscape-empty-topic@example.com")
    response = await client.post(
        "/discover/landscape", headers=_auth_headers(token), json=_landscape_body(topic="")
    )
    assert response.status_code == 422


async def test_create_landscape_streams_sse_formatted_events(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_run_landscape_search(monkeypatch, _events_done)
    token = await _register_and_login(client, "landscape-stream@example.com")

    response = await client.post("/discover/landscape", headers=_auth_headers(token), json=_landscape_body())

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: progress\n" in body
    assert "event: done\n" in body
    assert body.endswith("\n\n")


async def test_create_landscape_is_rate_limited_per_user(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_run_landscape_search(monkeypatch, _events_done)
    token = await _register_and_login(client, "landscape-ratelimited@example.com")

    responses = [
        await client.post("/discover/landscape", headers=_auth_headers(token), json=_landscape_body())
        for _ in range(6)
    ]

    assert responses[-1].status_code == 429


async def test_create_landscape_never_logs_submitted_api_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret_key = "sk-super-secret-landscape-13579"
    _mock_run_landscape_search(monkeypatch, _events_done)
    token = await _register_and_login(client, "landscape-no-log-leak@example.com")

    with caplog.at_level(logging.DEBUG, logger="app.discovery.router"):
        response = await client.post(
            "/discover/landscape", headers=_auth_headers(token), json=_landscape_body(api_key=secret_key)
        )

    assert response.status_code == 200
    for record in caplog.records:
        assert secret_key not in record.getMessage()


# ---- GET /discover/landscape/{id} -----------------------------------------


async def test_get_landscape_requires_auth(client: AsyncClient) -> None:
    response = await client.get(f"/discover/landscape/{uuid.uuid4()}")
    assert response.status_code == 401


async def test_get_landscape_not_found_is_404(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _raise(*args: object, **kwargs: object) -> None:
        raise TopicLandscapeNotFoundError("Topic landscape not found")

    monkeypatch.setattr("app.discovery.service.get_owned_landscape", _raise)
    token = await _register_and_login(client, "landscape-notfound@example.com")

    response = await client.get(f"/discover/landscape/{uuid.uuid4()}", headers=_auth_headers(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "topic_landscape_not_found"


async def test_get_landscape_returns_persisted_shape(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = await _register_and_login(client, "landscape-get@example.com")

    async def _fake_get_owned_landscape(db: object, landscape_id: uuid.UUID, user_id: uuid.UUID) -> TopicLandscape:
        return _sample_landscape(user_id)

    monkeypatch.setattr("app.discovery.service.get_owned_landscape", _fake_get_owned_landscape)

    response = await client.get(f"/discover/landscape/{uuid.uuid4()}", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["topic"] == "attention"
    assert len(body["papers"]) == 2
    assert len(body["clusters"]) == 1


# ---- GET /discover/landscape/{id}/graph -- exact frontend contract --------


async def test_get_landscape_graph_matches_exact_contract_shape(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = await _register_and_login(client, "landscape-graph@example.com")

    async def _fake_get_owned_landscape(db: object, landscape_id: uuid.UUID, user_id: uuid.UUID) -> TopicLandscape:
        return _sample_landscape(user_id)

    monkeypatch.setattr("app.discovery.service.get_owned_landscape", _fake_get_owned_landscape)

    response = await client.get(f"/discover/landscape/{uuid.uuid4()}/graph", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body.keys()) == {"nodes", "edges"}

    assert len(body["nodes"]) == 2
    for node in body["nodes"]:
        assert set(node.keys()) == {"id", "label", "color", "size"}
        assert isinstance(node["id"], str)
        assert isinstance(node["label"], str)
        assert isinstance(node["color"], str)

    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    assert set(edge.keys()) == {"source", "target", "relation", "weight"}
    assert edge["relation"] == "semantically_similar"
    assert {edge["source"], edge["target"]} == {"2001.00001", "2001.00002"}


# ---- GET/PUT /discover/profile ---------------------------------------------


async def test_get_profile_defaults_lazily(client: AsyncClient) -> None:
    token = await _register_and_login(client, "profile-default@example.com")

    response = await client.get("/discover/profile", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["interests"] == []
    assert body["level"] == "beginner"
    assert body["goals"] == []


async def test_put_profile_upserts_and_get_reflects_it(client: AsyncClient) -> None:
    token = await _register_and_login(client, "profile-upsert@example.com")

    put_response = await client.put(
        "/discover/profile",
        headers=_auth_headers(token),
        json={"interests": ["diffusion models"], "level": "intermediate", "goals": ["build a demo"]},
    )
    assert put_response.status_code == 200, put_response.text
    assert put_response.json()["interests"] == ["diffusion models"]

    get_response = await client.get("/discover/profile", headers=_auth_headers(token))
    assert get_response.json()["level"] == "intermediate"
    assert get_response.json()["goals"] == ["build a demo"]


async def test_put_profile_rejects_invalid_level(client: AsyncClient) -> None:
    token = await _register_and_login(client, "profile-invalid-level@example.com")

    response = await client.put(
        "/discover/profile",
        headers=_auth_headers(token),
        json={"interests": [], "level": "expert-wizard", "goals": []},
    )

    assert response.status_code == 422


async def test_put_profile_rejects_too_many_interests(client: AsyncClient) -> None:
    token = await _register_and_login(client, "profile-too-many-interests@example.com")

    response = await client.put(
        "/discover/profile",
        headers=_auth_headers(token),
        json={"interests": [f"topic {i}" for i in range(21)], "level": "beginner", "goals": []},
    )

    assert response.status_code == 422


# ---- GET /discover/recommendations -----------------------------------------


async def test_recommendations_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/discover/recommendations", params={"provider_id": "google", "embed_model": "m"})
    assert response.status_code == 401


async def test_recommendations_returns_service_result(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.discovery.schemas import RecommendationItem

    async def _fake_run_recommendations(*args: object, **kwargs: object) -> list[RecommendationItem]:
        return [
            RecommendationItem(
                arxiv_id="2001.00001",
                title="Paper A",
                authors=["Alice"],
                year=2021,
                abstract="abstract",
                relevance_score=0.9,
                explanation='Ranked for its similarity to the interest on your profile: "diffusion models" (similarity 0.90).',
            )
        ]

    monkeypatch.setattr("app.discovery.service.run_recommendations", _fake_run_recommendations)
    token = await _register_and_login(client, "recommendations-happy@example.com")

    response = await client.get(
        "/discover/recommendations",
        headers={**_auth_headers(token), "X-Provider-Api-Key": "sk-test"},
        params={"provider_id": "google", "embed_model": "m"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["explanation"]


async def test_recommendations_is_rate_limited_per_user(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_run_recommendations(*args: object, **kwargs: object) -> list:
        return []

    monkeypatch.setattr("app.discovery.service.run_recommendations", _fake_run_recommendations)
    token = await _register_and_login(client, "recommendations-ratelimited@example.com")

    responses = [
        await client.get(
            "/discover/recommendations", headers=_auth_headers(token), params={"provider_id": "google", "embed_model": "m"}
        )
        for _ in range(21)
    ]

    assert responses[-1].status_code == 429


async def test_recommendations_never_logs_api_key_header(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret_key = "sk-super-secret-recs-98765"

    async def _fake_run_recommendations(*args: object, **kwargs: object) -> list:
        return []

    monkeypatch.setattr("app.discovery.service.run_recommendations", _fake_run_recommendations)
    token = await _register_and_login(client, "recommendations-no-log-leak@example.com")

    with caplog.at_level(logging.DEBUG, logger="app.discovery.router"):
        response = await client.get(
            "/discover/recommendations",
            headers={**_auth_headers(token), "X-Provider-Api-Key": secret_key},
            params={"provider_id": "google", "embed_model": "m"},
        )

    assert response.status_code == 200
    for record in caplog.records:
        assert secret_key not in record.getMessage()
