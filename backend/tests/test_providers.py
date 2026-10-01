"""Contract tests for GET /providers."""

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


async def test_list_providers_returns_catalog(client: AsyncClient) -> None:
    token = await _register_and_login(client, "list-providers@example.com")

    response = await client.get("/providers", headers=_auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) > 0
    assert all({"id", "label", "auth", "capabilities"} <= entry.keys() for entry in body)


async def test_list_providers_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/providers")
    assert response.status_code == 401
