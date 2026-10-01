"""Contract tests for POST /auth/register, /auth/login, /auth/refresh, GET /auth/me."""

from httpx import AsyncClient

PASSWORD = "correct-horse-battery"


async def _register(client: AsyncClient, email: str, password: str = PASSWORD) -> None:
    response = await client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text


async def test_register_succeeds(client: AsyncClient) -> None:
    response = await client.post("/auth/register", json={"email": "new@example.com", "password": PASSWORD})

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert "id" in body
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_rejects_duplicate_email(client: AsyncClient) -> None:
    await _register(client, "dupe@example.com")

    response = await client.post("/auth/register", json={"email": "dupe@example.com", "password": "another-password"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


async def test_login_succeeds_with_correct_credentials(client: AsyncClient) -> None:
    await _register(client, "login@example.com")

    response = await client.post("/auth/login", json={"email": "login@example.com", "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_rejects_wrong_password(client: AsyncClient) -> None:
    await _register(client, "wrongpw@example.com")

    response = await client.post("/auth/login", json={"email": "wrongpw@example.com", "password": "not-the-password"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_protected_route_rejects_missing_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_protected_route_rejects_invalid_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_protected_route_accepts_valid_token(client: AsyncClient) -> None:
    await _register(client, "me@example.com")
    login_response = await client.post("/auth/login", json={"email": "me@example.com", "password": PASSWORD})
    access_token = login_response.json()["access_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


async def test_refresh_issues_new_working_access_token(client: AsyncClient) -> None:
    await _register(client, "refresh@example.com")
    login_response = await client.post("/auth/login", json={"email": "refresh@example.com", "password": PASSWORD})
    refresh_token = login_response.json()["refresh_token"]

    response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 200
    new_access_token = response.json()["access_token"]

    me_response = await client.get("/auth/me", headers={"Authorization": f"Bearer {new_access_token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "refresh@example.com"


async def test_refresh_rejects_access_token(client: AsyncClient) -> None:
    await _register(client, "wrongtype@example.com")
    login_response = await client.post("/auth/login", json={"email": "wrongtype@example.com", "password": PASSWORD})
    access_token = login_response.json()["access_token"]

    response = await client.post("/auth/refresh", json={"refresh_token": access_token})

    assert response.status_code == 401


async def test_login_is_rate_limited_per_ip(client: AsyncClient) -> None:
    await _register(client, "ratelimited-login@example.com")

    responses = [
        await client.post(
            "/auth/login", json={"email": "ratelimited-login@example.com", "password": "wrong"}
        )
        for _ in range(6)
    ]

    assert responses[-1].status_code == 429


async def test_register_is_rate_limited_per_ip(client: AsyncClient) -> None:
    responses = [
        await client.post("/auth/register", json={"email": f"ratelimited-{i}@example.com", "password": PASSWORD})
        for i in range(6)
    ]

    assert responses[-1].status_code == 429


async def test_refresh_is_rate_limited_per_ip(client: AsyncClient) -> None:
    await _register(client, "ratelimited-refresh@example.com")
    login_response = await client.post(
        "/auth/login", json={"email": "ratelimited-refresh@example.com", "password": PASSWORD}
    )
    refresh_token = login_response.json()["refresh_token"]

    responses = [
        await client.post("/auth/refresh", json={"refresh_token": refresh_token}) for _ in range(11)
    ]

    assert responses[-1].status_code == 429
