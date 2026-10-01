"""Contract tests for the ``/discover/roadmap*`` routes (Phase 6): auth,
ownership, rate limiting, SSE streaming, the tagged-union target validation,
and secret handling -- same conventions as ``test_router.py``'s Phase 5
route tests. ``app.discovery.service``'s roadmap pipeline/sequencing logic
itself is covered by ``test_roadmap_service_integration.py``/unit tests, not
re-verified here.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.discovery.exceptions import MilestoneNotFoundError, RoadmapNotFoundError
from app.discovery.service import AnalysisEvent
from app.models.roadmap import Roadmap
from tests.discovery.test_router import _auth_headers, _register_and_login

PASSWORD = "correct-horse-battery"


def _roadmap_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "target": {"type": "topic", "topic": "diffusion models"},
        "provider_id": "google",
        "api_key": "sk-test",
        "model": "m",
        "embed_model": "m",
    }
    body.update(overrides)
    return body


async def _events_done() -> AsyncIterator[AnalysisEvent]:
    yield AnalysisEvent(type="progress", stage="roadmap", message="Configuring AI provider")
    yield AnalysisEvent(
        type="done",
        stage="roadmap",
        data={
            "id": str(uuid.uuid4()),
            "target_description": "diffusion models",
            "target_paper_id": None,
            "concepts": [],
            "edges": [],
            "milestones": [],
            "overview": "An overview.",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        },
    )


def _mock_run_roadmap_generation(monkeypatch: pytest.MonkeyPatch, events_factory: object) -> None:
    monkeypatch.setattr("app.discovery.service.run_roadmap_generation", lambda **kwargs: events_factory())


def _sample_roadmap(user_id: uuid.UUID) -> Roadmap:
    now = datetime.now(timezone.utc)
    return Roadmap(
        id=uuid.uuid4(),
        user_id=user_id,
        target_description="attention",
        target_paper_id=None,
        concepts=[
            {
                "id": "c1",
                "name": "Attention",
                "description": "d",
                "source_paper_id": None,
                "source_arxiv_id": "2001.00001",
                "grounding_excerpt": "e",
                "verification_status": "verified",
            }
        ],
        edges=[],
        milestones=[
            {
                "id": "m1",
                "order": 0,
                "paper_id": None,
                "arxiv_id": "2001.00001",
                "title": "Paper A",
                "concept_ids": ["c1"],
                "status": "available",
            },
            {
                "id": "m2",
                "order": 1,
                "paper_id": None,
                "arxiv_id": "2001.00002",
                "title": "Paper B",
                "concept_ids": [],
                "status": "locked",
            },
        ],
        overview="An overview of the roadmap.",
        created_at=now,
        updated_at=now,
    )


# ---- POST /discover/roadmap -------------------------------------------


async def test_create_roadmap_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/discover/roadmap", json=_roadmap_body())
    assert response.status_code == 401


async def test_create_roadmap_rejects_body_missing_target(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_run_roadmap_generation(monkeypatch, _events_done)
    token = await _register_and_login(client, "roadmap-missing-target@example.com")

    response = await client.post(
        "/discover/roadmap",
        headers=_auth_headers(token),
        json={"provider_id": "google", "api_key": "sk-test"},
    )

    assert response.status_code == 422


async def test_create_roadmap_rejects_unknown_target_type(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_run_roadmap_generation(monkeypatch, _events_done)
    token = await _register_and_login(client, "roadmap-unknown-target-type@example.com")

    response = await client.post(
        "/discover/roadmap",
        headers=_auth_headers(token),
        json=_roadmap_body(target={"type": "not-a-real-type"}),
    )

    assert response.status_code == 422


async def test_create_roadmap_rejects_paper_target_missing_paper_id(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_run_roadmap_generation(monkeypatch, _events_done)
    token = await _register_and_login(client, "roadmap-paper-missing-id@example.com")

    response = await client.post(
        "/discover/roadmap",
        headers=_auth_headers(token),
        json=_roadmap_body(target={"type": "paper"}),
    )

    assert response.status_code == 422


async def test_create_roadmap_paper_target_is_404_when_paper_not_owned(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_run_roadmap_generation(monkeypatch, _events_done)
    token = await _register_and_login(client, "roadmap-paper-not-owned@example.com")

    response = await client.post(
        "/discover/roadmap",
        headers=_auth_headers(token),
        json=_roadmap_body(target={"type": "paper", "paper_id": str(uuid.uuid4())}),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_create_roadmap_streams_sse_formatted_events(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_run_roadmap_generation(monkeypatch, _events_done)
    token = await _register_and_login(client, "roadmap-stream@example.com")

    response = await client.post("/discover/roadmap", headers=_auth_headers(token), json=_roadmap_body())

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: progress\n" in body
    assert "event: done\n" in body
    assert body.endswith("\n\n")


async def test_create_roadmap_is_rate_limited_per_user(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_run_roadmap_generation(monkeypatch, _events_done)
    token = await _register_and_login(client, "roadmap-ratelimited@example.com")

    responses = [
        await client.post("/discover/roadmap", headers=_auth_headers(token), json=_roadmap_body())
        for _ in range(6)
    ]

    assert responses[-1].status_code == 429


async def test_create_roadmap_never_logs_submitted_api_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret_key = "sk-super-secret-roadmap-24680"
    _mock_run_roadmap_generation(monkeypatch, _events_done)
    token = await _register_and_login(client, "roadmap-no-log-leak@example.com")

    with caplog.at_level(logging.DEBUG, logger="app.discovery.router"):
        response = await client.post(
            "/discover/roadmap", headers=_auth_headers(token), json=_roadmap_body(api_key=secret_key)
        )

    assert response.status_code == 200
    for record in caplog.records:
        assert secret_key not in record.getMessage()


# ---- GET /discover/roadmap/{id} ----------------------------------------


async def test_get_roadmap_requires_auth(client: AsyncClient) -> None:
    response = await client.get(f"/discover/roadmap/{uuid.uuid4()}")
    assert response.status_code == 401


async def test_get_roadmap_not_found_is_404(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _raise(*args: object, **kwargs: object) -> None:
        raise RoadmapNotFoundError("Roadmap not found")

    monkeypatch.setattr("app.discovery.service.get_owned_roadmap", _raise)
    token = await _register_and_login(client, "roadmap-notfound@example.com")

    response = await client.get(f"/discover/roadmap/{uuid.uuid4()}", headers=_auth_headers(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "roadmap_not_found"


async def test_get_roadmap_returns_persisted_shape(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = await _register_and_login(client, "roadmap-get@example.com")

    async def _fake_get_owned_roadmap(db: object, roadmap_id: uuid.UUID, user_id: uuid.UUID) -> Roadmap:
        return _sample_roadmap(user_id)

    monkeypatch.setattr("app.discovery.service.get_owned_roadmap", _fake_get_owned_roadmap)

    response = await client.get(f"/discover/roadmap/{uuid.uuid4()}", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target_description"] == "attention"
    assert body["target_paper_id"] is None
    assert len(body["concepts"]) == 1
    assert len(body["milestones"]) == 2
    assert body["milestones"][0]["status"] == "available"
    assert body["milestones"][1]["status"] == "locked"


# ---- GET /discover/roadmaps ---------------------------------------------


async def test_list_roadmaps_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/discover/roadmaps")
    assert response.status_code == 401


async def test_list_roadmaps_returns_summary_shape(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = await _register_and_login(client, "roadmap-list@example.com")

    async def _fake_list_roadmaps(db: object, user_id: uuid.UUID) -> list[Roadmap]:
        return [_sample_roadmap(user_id)]

    monkeypatch.setattr("app.discovery.service.list_roadmaps", _fake_list_roadmaps)

    response = await client.get("/discover/roadmaps", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["target_description"] == "attention"
    assert body[0]["milestone_count"] == 2
    assert body[0]["completed_count"] == 0


# ---- PATCH /discover/roadmap/{id}/milestones/{milestone_id} ---------------


async def test_update_milestone_requires_auth(client: AsyncClient) -> None:
    response = await client.patch(
        f"/discover/roadmap/{uuid.uuid4()}/milestones/m1", json={"status": "completed"}
    )
    assert response.status_code == 401


async def test_update_milestone_rejects_invalid_status(client: AsyncClient) -> None:
    token = await _register_and_login(client, "roadmap-milestone-invalid-status@example.com")

    response = await client.patch(
        f"/discover/roadmap/{uuid.uuid4()}/milestones/m1",
        headers=_auth_headers(token),
        json={"status": "locked"},  # not settable by a user, only by the system
    )

    assert response.status_code == 422


async def test_update_milestone_not_found_roadmap_is_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise(*args: object, **kwargs: object) -> None:
        raise RoadmapNotFoundError("Roadmap not found")

    monkeypatch.setattr("app.discovery.service.update_milestone_status", _raise)
    token = await _register_and_login(client, "roadmap-milestone-roadmap-404@example.com")

    response = await client.patch(
        f"/discover/roadmap/{uuid.uuid4()}/milestones/m1",
        headers=_auth_headers(token),
        json={"status": "completed"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "roadmap_not_found"


async def test_update_milestone_not_found_milestone_is_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise(*args: object, **kwargs: object) -> None:
        raise MilestoneNotFoundError("Milestone not found")

    monkeypatch.setattr("app.discovery.service.update_milestone_status", _raise)
    token = await _register_and_login(client, "roadmap-milestone-404@example.com")

    response = await client.patch(
        f"/discover/roadmap/{uuid.uuid4()}/milestones/does-not-exist",
        headers=_auth_headers(token),
        json={"status": "completed"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "milestone_not_found"


async def test_update_milestone_returns_updated_roadmap(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = await _register_and_login(client, "roadmap-milestone-update@example.com")

    async def _fake_update(
        db: object, roadmap_id: uuid.UUID, user_id: uuid.UUID, milestone_id: str, status: str
    ) -> Roadmap:
        roadmap = _sample_roadmap(user_id)
        roadmap.milestones = [{**m, "status": status} if m["id"] == milestone_id else m for m in roadmap.milestones]
        return roadmap

    monkeypatch.setattr("app.discovery.service.update_milestone_status", _fake_update)

    response = await client.patch(
        f"/discover/roadmap/{uuid.uuid4()}/milestones/m2",
        headers=_auth_headers(token),
        json={"status": "completed"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    statuses = {m["id"]: m["status"] for m in body["milestones"]}
    assert statuses["m2"] == "completed"
