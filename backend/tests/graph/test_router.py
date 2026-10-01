"""Contract tests for ``/graph`` and ``/graph/papers/{id}/neighbors``: auth,
ownership (404-not-403), rate limiting, embed ``NotSupportedError`` surfaced
cleanly, and that a submitted API key is never logged -- same pattern as
``tests/discovery/test_router.py``.
"""

import logging
import uuid

import pytest
from httpx import AsyncClient

from app.graph.schemas import LibraryGraphResponse
from app.providers.errors import NotSupportedError

PASSWORD = "correct-horse-battery"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    login_response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_response.status_code == 200, login_response.text
    return login_response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mock_build_library_graph(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    async def _fake(*args: object, **kwargs: object) -> object:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("app.graph.service.build_library_graph", _fake)


def _mock_build_neighbors_graph(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    async def _fake(*args: object, **kwargs: object) -> object:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("app.graph.service.build_paper_neighbors_graph", _fake)


# ---- GET /graph -------------------------------------------------------------


async def test_get_graph_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/graph", params={"provider_id": "google", "embed_model": "m"})
    assert response.status_code == 401


async def test_get_graph_returns_service_result(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_build_library_graph(monkeypatch, LibraryGraphResponse(nodes=[], edges=[]))
    token = await _register_and_login(client, "graph-happy@example.com")

    response = await client.get(
        "/graph",
        headers={**_auth_headers(token), "X-Provider-Api-Key": "sk-test"},
        params={"provider_id": "google", "embed_model": "m"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"nodes": [], "edges": []}


async def test_get_graph_matches_neural_map_contract_shape(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.graph.schemas import GraphEdge, GraphNode

    _mock_build_library_graph(
        monkeypatch,
        LibraryGraphResponse(
            nodes=[GraphNode(id=str(uuid.uuid4()), label="Paper A", color="#6366f1", size=None)],
            edges=[
                GraphEdge(
                    source=str(uuid.uuid4()), target=str(uuid.uuid4()), relation="semantically_similar", weight=0.9
                )
            ],
        ),
    )
    token = await _register_and_login(client, "graph-contract@example.com")

    response = await client.get(
        "/graph", headers={**_auth_headers(token), "X-Provider-Api-Key": "sk-test"}, params={"provider_id": "google", "embed_model": "m"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body.keys()) == {"nodes", "edges"}
    assert set(body["nodes"][0].keys()) == {"id", "label", "color", "size"}
    assert set(body["edges"][0].keys()) == {"source", "target", "relation", "weight"}
    assert body["edges"][0]["relation"] == "semantically_similar"


async def test_get_graph_embed_not_supported_is_surfaced_cleanly(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_build_library_graph(monkeypatch, NotSupportedError("This provider cannot embed"))
    token = await _register_and_login(client, "graph-not-supported@example.com")

    response = await client.get(
        "/graph", headers={**_auth_headers(token), "X-Provider-Api-Key": "sk-test"}, params={"provider_id": "google", "embed_model": "m"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "provider_capability_not_supported"


async def test_get_graph_unknown_provider_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "graph-unknown-provider@example.com")

    response = await client.get(
        "/graph", headers=_auth_headers(token), params={"provider_id": "not-a-real-provider", "embed_model": "m"}
    )

    assert response.status_code == 404


async def test_get_graph_is_rate_limited_per_user(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_build_library_graph(monkeypatch, LibraryGraphResponse(nodes=[], edges=[]))
    token = await _register_and_login(client, "graph-ratelimited@example.com")

    responses = [
        await client.get(
            "/graph",
            headers={**_auth_headers(token), "X-Provider-Api-Key": "sk-test"},
            params={"provider_id": "google", "embed_model": "m"},
        )
        for _ in range(21)
    ]

    assert responses[-1].status_code == 429


async def test_get_graph_never_logs_api_key_header(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _mock_build_library_graph(monkeypatch, LibraryGraphResponse(nodes=[], edges=[]))
    secret_key = "sk-super-secret-graph-24680"
    token = await _register_and_login(client, "graph-no-log-leak@example.com")

    with caplog.at_level(logging.DEBUG, logger="app.graph.router"):
        response = await client.get(
            "/graph",
            headers={**_auth_headers(token), "X-Provider-Api-Key": secret_key},
            params={"provider_id": "google", "embed_model": "m"},
        )

    assert response.status_code == 200
    for record in caplog.records:
        assert secret_key not in record.getMessage()


# ---- GET /graph/papers/{id}/neighbors ---------------------------------------


async def test_get_neighbors_requires_auth(client: AsyncClient) -> None:
    response = await client.get(f"/graph/papers/{uuid.uuid4()}/neighbors", params={"provider_id": "google", "embed_model": "m"})
    assert response.status_code == 401


async def test_get_neighbors_not_owned_paper_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "graph-neighbors-notfound@example.com")

    response = await client.get(
        f"/graph/papers/{uuid.uuid4()}/neighbors",
        headers={**_auth_headers(token), "X-Provider-Api-Key": "sk-test"},
        params={"provider_id": "google", "embed_model": "m"},
    )
    # No service mocking needed: a random paper_id is never owned by this
    # fresh user, so the real service raises PaperNotFoundError before any
    # embed call is attempted.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_get_neighbors_returns_service_result(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_build_neighbors_graph(monkeypatch, LibraryGraphResponse(nodes=[], edges=[]))
    token = await _register_and_login(client, "graph-neighbors-happy@example.com")

    response = await client.get(
        f"/graph/papers/{uuid.uuid4()}/neighbors",
        headers={**_auth_headers(token), "X-Provider-Api-Key": "sk-test"},
        params={"provider_id": "google", "embed_model": "m"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"nodes": [], "edges": []}
