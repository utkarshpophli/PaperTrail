"""Contract tests for ``/collections/*``: CRUD, ownership (404-not-403),
idempotent paper add/remove, and rate limiting -- same pattern as
``tests/discovery/test_router.py``.
"""

import uuid

from httpx import AsyncClient

PASSWORD = "correct-horse-battery"


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


# ---- POST /collections ------------------------------------------------------


async def test_create_collection_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/collections", json={"name": "My reading list"})
    assert response.status_code == 401


async def test_create_collection_returns_empty_paper_ids(client: AsyncClient) -> None:
    token = await _register_and_login(client, "collections-create@example.com")

    response = await client.post("/collections", headers=_auth_headers(token), json={"name": "My reading list"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "My reading list"
    assert body["paper_ids"] == []


async def test_create_collection_rejects_empty_name(client: AsyncClient) -> None:
    token = await _register_and_login(client, "collections-empty-name@example.com")

    response = await client.post("/collections", headers=_auth_headers(token), json={"name": ""})

    assert response.status_code == 422


async def test_create_collection_is_rate_limited_per_user(client: AsyncClient) -> None:
    token = await _register_and_login(client, "collections-ratelimited@example.com")

    responses = [
        await client.post("/collections", headers=_auth_headers(token), json={"name": f"list {i}"})
        for i in range(11)
    ]

    assert responses[-1].status_code == 429


# ---- GET /collections / GET /collections/{id} ------------------------------


async def test_list_collections_scoped_to_owner(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "collections-list-a@example.com")
    token_b = await _register_and_login(client, "collections-list-b@example.com")

    await client.post("/collections", headers=_auth_headers(token_a), json={"name": "A's list"})
    await client.post("/collections", headers=_auth_headers(token_b), json={"name": "B's list"})

    response = await client.get("/collections", headers=_auth_headers(token_a))

    assert response.status_code == 200, response.text
    names = [c["name"] for c in response.json()]
    assert names == ["A's list"]


async def test_get_collection_not_owned_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "collections-get-a@example.com")
    token_b = await _register_and_login(client, "collections-get-b@example.com")

    create_response = await client.post("/collections", headers=_auth_headers(token_a), json={"name": "A's list"})
    collection_id = create_response.json()["id"]

    response = await client.get(f"/collections/{collection_id}", headers=_auth_headers(token_b))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "collection_not_found"


async def test_get_collection_missing_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "collections-get-missing@example.com")

    response = await client.get(f"/collections/{uuid.uuid4()}", headers=_auth_headers(token))

    assert response.status_code == 404


# ---- POST/DELETE /collections/{id}/papers/{paper_id} -----------------------


async def test_add_paper_requires_ownership_of_both_resources(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "collections-add-a@example.com")
    token_b = await _register_and_login(client, "collections-add-b@example.com")

    collection_id = (
        await client.post("/collections", headers=_auth_headers(token_a), json={"name": "A's list"})
    ).json()["id"]
    paper_id = await _create_paper(client, token_b)

    # A owns the collection but not the paper -- must 404, never silently add
    # a paper the requester doesn't own.
    response = await client.post(
        f"/collections/{collection_id}/papers/{paper_id}", headers=_auth_headers(token_a)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


async def test_add_paper_not_owned_collection_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "collections-add-collection-a@example.com")
    token_b = await _register_and_login(client, "collections-add-collection-b@example.com")

    collection_id = (
        await client.post("/collections", headers=_auth_headers(token_b), json={"name": "B's list"})
    ).json()["id"]
    paper_id = await _create_paper(client, token_a)

    response = await client.post(
        f"/collections/{collection_id}/papers/{paper_id}", headers=_auth_headers(token_a)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "collection_not_found"


async def test_add_paper_is_idempotent(client: AsyncClient) -> None:
    token = await _register_and_login(client, "collections-add-idempotent@example.com")
    collection_id = (
        await client.post("/collections", headers=_auth_headers(token), json={"name": "list"})
    ).json()["id"]
    paper_id = await _create_paper(client, token)

    first = await client.post(f"/collections/{collection_id}/papers/{paper_id}", headers=_auth_headers(token))
    second = await client.post(f"/collections/{collection_id}/papers/{paper_id}", headers=_auth_headers(token))

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["paper_ids"] == [paper_id]


async def test_remove_paper_is_noop_when_not_present(client: AsyncClient) -> None:
    token = await _register_and_login(client, "collections-remove-noop@example.com")
    collection_id = (
        await client.post("/collections", headers=_auth_headers(token), json={"name": "list"})
    ).json()["id"]
    paper_id = await _create_paper(client, token)

    response = await client.delete(
        f"/collections/{collection_id}/papers/{paper_id}", headers=_auth_headers(token)
    )

    assert response.status_code == 200, response.text
    assert response.json()["paper_ids"] == []


async def test_add_then_remove_paper(client: AsyncClient) -> None:
    token = await _register_and_login(client, "collections-add-remove@example.com")
    collection_id = (
        await client.post("/collections", headers=_auth_headers(token), json={"name": "list"})
    ).json()["id"]
    paper_id = await _create_paper(client, token)

    await client.post(f"/collections/{collection_id}/papers/{paper_id}", headers=_auth_headers(token))
    remove_response = await client.delete(
        f"/collections/{collection_id}/papers/{paper_id}", headers=_auth_headers(token)
    )

    assert remove_response.status_code == 200, remove_response.text
    assert remove_response.json()["paper_ids"] == []
