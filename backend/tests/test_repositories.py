"""Contract tests for ``/papers/{id}/repositories*``: linking, listing,
unlinking, detection (never auto-persists), ownership (404-not-403), rate
limiting, and token-never-logged -- same pattern as ``tests/test_collections.py``.

``app.coderesearch.service.fetch_repo_metadata``/``search_repos_by_query``
are mocked here -- the one sanctioned internal-boundary mock (TESTING.md)
for the real GitHub API call, same pattern ``tests/test_evidence.py`` used
for ``run_analysis``.
"""

import logging
import uuid

import pytest
from httpx import AsyncClient

from app.coderesearch.github_client import RepoMetadata

PASSWORD = "correct-horse-battery"

_FAKE_METADATA = RepoMetadata(
    owner="openai", name="gpt-3", description="GPT-3 paper code", stars=1000, url="https://github.com/openai/gpt-3"
)


async def _register_and_login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    login_response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_response.status_code == 200, login_response.text
    return login_response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_paper(client: AsyncClient, token: str, title: str = "test.pdf") -> str:
    response = await client.post(
        "/papers/upload",
        headers=_auth_headers(token),
        files={"file": (title, b"%PDF-fake-content", "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _mock_fetch_repo_metadata(monkeypatch: pytest.MonkeyPatch, metadata: RepoMetadata = _FAKE_METADATA) -> None:
    async def _fetch(owner: str, repo: str, token: str | None) -> RepoMetadata:
        return metadata

    monkeypatch.setattr("app.coderesearch.service.fetch_repo_metadata", _fetch)


def _mock_search_repos(monkeypatch: pytest.MonkeyPatch, results: list[RepoMetadata]) -> None:
    async def _search(query: str, token: str | None) -> list[RepoMetadata]:
        return results

    monkeypatch.setattr("app.coderesearch.service.search_repos_by_query", _search)


# ---- POST /papers/{id}/repositories ----------------------------------------


async def test_create_repository_requires_auth(client: AsyncClient) -> None:
    response = await client.post(f"/papers/{uuid.uuid4()}/repositories", json={"url": "https://github.com/a/b"})
    assert response.status_code == 401


async def test_create_repository_link_persists_user_linked_with_null_confidence(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_fetch_repo_metadata(monkeypatch)
    token = await _register_and_login(client, "repo-create@example.com")
    paper_id = await _create_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/repositories",
        headers=_auth_headers(token),
        json={"url": "https://github.com/openai/gpt-3"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["owner"] == "openai"
    assert body["source"] == "user_linked"
    assert body["confidence"] is None


async def test_create_repository_rejects_non_github_url(client: AsyncClient) -> None:
    token = await _register_and_login(client, "repo-invalid-url@example.com")
    paper_id = await _create_paper(client, token)

    response = await client.post(
        f"/papers/{paper_id}/repositories",
        headers=_auth_headers(token),
        json={"url": "https://evil.example.com/openai/gpt-3"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_repository_url"


async def test_create_repository_requires_ownership_of_paper(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_fetch_repo_metadata(monkeypatch)
    token_a = await _register_and_login(client, "repo-owner-a@example.com")
    token_b = await _register_and_login(client, "repo-owner-b@example.com")
    paper_id = await _create_paper(client, token_b)

    response = await client.post(
        f"/papers/{paper_id}/repositories",
        headers=_auth_headers(token_a),
        json={"url": "https://github.com/openai/gpt-3"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_create_repository_never_logs_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret_token = "ghp_super-secret-do-not-log-98765"
    _mock_fetch_repo_metadata(monkeypatch)
    token = await _register_and_login(client, "repo-no-log-leak@example.com")
    paper_id = await _create_paper(client, token)

    with caplog.at_level(logging.DEBUG, logger="app.coderesearch.router"):
        response = await client.post(
            f"/papers/{paper_id}/repositories",
            headers=_auth_headers(token),
            json={"url": "https://github.com/openai/gpt-3", "token": secret_token},
        )

    assert response.status_code == 201, response.text
    for record in caplog.records:
        assert secret_token not in record.getMessage()


async def test_create_repository_is_rate_limited_per_user(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_fetch_repo_metadata(monkeypatch)
    token = await _register_and_login(client, "repo-ratelimited@example.com")
    paper_id = await _create_paper(client, token)

    responses = [
        await client.post(
            f"/papers/{paper_id}/repositories",
            headers=_auth_headers(token),
            json={"url": "https://github.com/openai/gpt-3"},
        )
        for _ in range(21)
    ]

    assert responses[-1].status_code == 429


# ---- GET /papers/{id}/repositories ------------------------------------------


async def test_list_repositories_requires_ownership(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_fetch_repo_metadata(monkeypatch)
    token_a = await _register_and_login(client, "repo-list-a@example.com")
    token_b = await _register_and_login(client, "repo-list-b@example.com")
    paper_id = await _create_paper(client, token_a)
    await client.post(
        f"/papers/{paper_id}/repositories", headers=_auth_headers(token_a), json={"url": "https://github.com/openai/gpt-3"}
    )

    owner_response = await client.get(f"/papers/{paper_id}/repositories", headers=_auth_headers(token_a))
    assert owner_response.status_code == 200
    assert len(owner_response.json()) == 1

    intruder_response = await client.get(f"/papers/{paper_id}/repositories", headers=_auth_headers(token_b))
    assert intruder_response.status_code == 404
    assert intruder_response.json()["error"]["code"] == "paper_not_found"


# ---- DELETE /papers/{id}/repositories/{repository_id} ----------------------


async def test_delete_repository_unlinks_it(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_fetch_repo_metadata(monkeypatch)
    token = await _register_and_login(client, "repo-delete@example.com")
    paper_id = await _create_paper(client, token)
    link_response = await client.post(
        f"/papers/{paper_id}/repositories", headers=_auth_headers(token), json={"url": "https://github.com/openai/gpt-3"}
    )
    repository_id = link_response.json()["id"]

    delete_response = await client.delete(
        f"/papers/{paper_id}/repositories/{repository_id}", headers=_auth_headers(token)
    )
    assert delete_response.status_code == 204

    list_response = await client.get(f"/papers/{paper_id}/repositories", headers=_auth_headers(token))
    assert list_response.json() == []


async def test_delete_missing_repository_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "repo-delete-missing@example.com")
    paper_id = await _create_paper(client, token)

    response = await client.delete(f"/papers/{paper_id}/repositories/{uuid.uuid4()}", headers=_auth_headers(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "repository_not_found"


async def test_delete_repository_linked_to_a_different_paper_is_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repository_id that's real but belongs to a *different* paper (same
    user, so paper-ownership alone wouldn't catch this) must still 404 --
    regression test for service.unlink_repository's paper_id-scoped lookup,
    not just an id lookup."""
    _mock_fetch_repo_metadata(monkeypatch)
    token = await _register_and_login(client, "repo-delete-cross-paper@example.com")
    paper_a = await _create_paper(client, token, title="a.pdf")
    paper_b = await _create_paper(client, token, title="b.pdf")
    link_response = await client.post(
        f"/papers/{paper_a}/repositories", headers=_auth_headers(token), json={"url": "https://github.com/openai/gpt-3"}
    )
    repository_id = link_response.json()["id"]

    response = await client.delete(f"/papers/{paper_b}/repositories/{repository_id}", headers=_auth_headers(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "repository_not_found"
    still_there = await client.get(f"/papers/{paper_a}/repositories", headers=_auth_headers(token))
    assert len(still_there.json()) == 1


# ---- POST /papers/{id}/repositories/detect ----------------------------------


async def test_detect_repositories_returns_candidates_without_persisting(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_search_repos(monkeypatch, [_FAKE_METADATA])
    token = await _register_and_login(client, "repo-detect@example.com")
    paper_id = await _create_paper(client, token)

    detect_response = await client.post(
        f"/papers/{paper_id}/repositories/detect", headers=_auth_headers(token), json={}
    )

    assert detect_response.status_code == 200, detect_response.text
    candidates = detect_response.json()
    assert len(candidates) == 1
    assert candidates[0]["owner"] == "openai"
    assert candidates[0]["confidence"] < 1.0  # unverified, distinct from a confirmed link's implicit full trust
    assert "id" not in candidates[0]  # never looks like a persisted Repository row

    # Detection must never auto-persist -- confirming this candidate requires
    # a separate POST /papers/{id}/repositories call.
    list_response = await client.get(f"/papers/{paper_id}/repositories", headers=_auth_headers(token))
    assert list_response.json() == []


async def test_detect_repositories_requires_ownership(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_search_repos(monkeypatch, [_FAKE_METADATA])
    token_a = await _register_and_login(client, "repo-detect-owner-a@example.com")
    token_b = await _register_and_login(client, "repo-detect-owner-b@example.com")
    paper_id = await _create_paper(client, token_b)

    response = await client.post(f"/papers/{paper_id}/repositories/detect", headers=_auth_headers(token_a), json={})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_detect_repositories_is_rate_limited_per_user(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_search_repos(monkeypatch, [])
    token = await _register_and_login(client, "repo-detect-ratelimited@example.com")
    paper_id = await _create_paper(client, token)

    responses = [
        await client.post(f"/papers/{paper_id}/repositories/detect", headers=_auth_headers(token), json={})
        for _ in range(21)
    ]

    assert responses[-1].status_code == 429
