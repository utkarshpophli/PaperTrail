"""Contract tests for POST /providers/{id}/models and /providers/{id}/test-model.

``registry.build_provider`` is replaced by a factory that builds the REAL
adapter with a mocked httpx transport, so the routes are exercised end to end
(adapter parsing, error mapping, redaction) without a live network call.
"""

import json
import logging
from collections.abc import Callable

import httpx
import pytest
from httpx import AsyncClient

from app.providers.anthropic import AnthropicProvider
from app.providers.llama_cpp import LlamaCppProvider
from app.providers.openai import OpenAIProvider

PASSWORD = "correct-horse-battery"
SECRET_KEY = "sk-super-secret-do-not-log-12345"

Handler = Callable[[httpx.Request], httpx.Response]


async def _token(client: AsyncClient, email: str) -> dict[str, str]:
    assert (await client.post("/auth/register", json={"email": email, "password": PASSWORD})).status_code == 201
    login = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _use_transport(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    transport = httpx.MockTransport(handler)

    def build(provider_id: str, *, api_key: str | None = None, endpoint: str | None = None) -> object:
        if provider_id == "openai":
            return OpenAIProvider(api_key=api_key or "", transport=transport)
        if provider_id == "anthropic":
            return AnthropicProvider(api_key=api_key or "", transport=transport)
        if provider_id == "llama_cpp":
            return LlamaCppProvider(endpoint=endpoint or "", transport=transport)
        raise AssertionError(provider_id)

    monkeypatch.setattr("app.providers.registry.build_provider", build)


def _models_payload() -> dict:
    return {
        "data": [
            {"id": "gpt-4o-mini"},
            {"id": "text-embedding-3-small"},
            {"id": "whisper-1"},
            {"id": "Zeta-chat"},
            {"id": "alpha-chat"},
        ]
    }


# --- POST /providers/{id}/models -------------------------------------------


async def test_models_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/providers/openai/models", json={"api_key": SECRET_KEY})
    assert response.status_code == 401


async def test_models_unknown_provider_is_404(client: AsyncClient) -> None:
    headers = await _token(client, "models-unknown@example.com")
    response = await client.post("/providers/nope/models", headers=headers, json={"api_key": SECRET_KEY})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "provider_not_found"


@pytest.mark.parametrize(
    ("provider_id", "body"),
    [
        ("openai", {}),
        ("openai", {"api_key": SECRET_KEY, "endpoint": "http://127.0.0.1:1234"}),
        ("lmstudio", {}),
        ("lmstudio", {"endpoint": "http://127.0.0.1:1234", "api_key": SECRET_KEY}),
        ("llama_cpp", {"api_key": SECRET_KEY}),
    ],
)
async def test_models_credential_shape_errors(client: AsyncClient, provider_id: str, body: dict) -> None:
    headers = await _token(client, f"models-shape-{provider_id}-{len(body)}@example.com")
    response = await client.post(f"/providers/{provider_id}/models", headers=headers, json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_validation_error"
    assert SECRET_KEY not in response.text


async def test_models_live_returns_chat_models_only_sorted_by_label(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_transport(monkeypatch, lambda r: httpx.Response(200, json=_models_payload()))
    headers = await _token(client, "models-live@example.com")

    response = await client.post("/providers/openai/models", headers=headers, json={"api_key": SECRET_KEY})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "models": [
            {"id": "alpha-chat", "label": "alpha-chat", "context_length": None, "kind": "chat"},
            {"id": "gpt-4o-mini", "label": "gpt-4o-mini", "context_length": None, "kind": "chat"},
            {"id": "Zeta-chat", "label": "Zeta-chat", "context_length": None, "kind": "chat"},
        ],
    }


async def test_models_unreachable_provider_is_a_real_error_not_a_static_list(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect, key {SECRET_KEY}", request=request)

    _use_transport(monkeypatch, handler)
    headers = await _token(client, "models-unreachable@example.com")

    response = await client.post("/providers/openai/models", headers=headers, json={"api_key": SECRET_KEY})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert SECRET_KEY not in response.text


async def test_models_upstream_failure_never_echoes_upstream_body(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    banner = "internal-banner-do-not-leak-9.9.9"
    _use_transport(monkeypatch, lambda r: httpx.Response(500, text=banner))
    headers = await _token(client, "models-nobody@example.com")

    response = await client.post("/providers/openai/models", headers=headers, json={"api_key": SECRET_KEY})

    assert response.status_code == 502
    assert banner not in response.text


async def test_models_rejected_credential_is_401_not_a_fallback(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_transport(monkeypatch, lambda r: httpx.Response(401, json={"error": "bad key"}))
    headers = await _token(client, "models-401@example.com")

    response = await client.post("/providers/anthropic/models", headers=headers, json={"api_key": SECRET_KEY})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "provider_authentication_failed"
    assert SECRET_KEY not in response.text


async def test_models_local_provider_unreachable_is_a_real_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _use_transport(monkeypatch, handler)
    headers = await _token(client, "models-local-down@example.com")

    response = await client.post(
        "/providers/llama_cpp/models", headers=headers, json={"endpoint": "http://127.0.0.1:8080"}
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_unavailable"


async def test_models_rejects_non_loopback_local_endpoint(client: AsyncClient) -> None:
    headers = await _token(client, "models-ssrf@example.com")

    response = await client.post("/providers/lmstudio/models", headers=headers, json={"endpoint": "http://10.0.0.5:1234"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "provider_invalid_config"


async def test_models_is_rate_limited(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_transport(monkeypatch, lambda r: httpx.Response(200, json=_models_payload()))
    headers = await _token(client, "models-ratelimit@example.com")

    statuses = [
        (await client.post("/providers/openai/models", headers=headers, json={"api_key": SECRET_KEY})).status_code
        for _ in range(11)
    ]

    assert statuses[:10] == [200] * 10 and statuses[10] == 429


async def test_models_never_logs_the_api_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"upstream echoed {SECRET_KEY}")

    _use_transport(monkeypatch, handler)
    headers = await _token(client, "models-nolog@example.com")

    with caplog.at_level(logging.DEBUG):
        response = await client.post("/providers/openai/models", headers=headers, json={"api_key": SECRET_KEY})

    assert response.status_code == 502
    assert caplog.records, "caplog captured nothing - the assertion below would be vacuous"
    # The adapter logs the upstream failure body for operators; it must never
    # carry the credential even when upstream echoes it.
    assert any("provider_request_failed" in r.getMessage() for r in caplog.records)
    assert SECRET_KEY not in caplog.text
    assert SECRET_KEY not in response.text


# --- POST /providers/{id}/test-model ---------------------------------------


async def test_test_model_pings_with_the_exact_model(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    _use_transport(monkeypatch, handler)
    headers = await _token(client, "testmodel-ok@example.com")

    response = await client.post(
        "/providers/openai/test-model", headers=headers, json={"api_key": SECRET_KEY, "model": "gpt-4.1-mini"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0
    assert seen[0]["model"] == "gpt-4.1-mini"


async def test_test_model_with_embedding_kind_id_pings_via_embed_not_generate(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})

    _use_transport(monkeypatch, handler)
    headers = await _token(client, "testmodel-embed@example.com")

    response = await client.post(
        "/providers/openai/test-model",
        headers=headers,
        json={"api_key": SECRET_KEY, "model": "text-embedding-3-small"},
    )

    assert response.status_code == 200, response.text
    assert seen[0]["model"] == "text-embedding-3-small"
    assert "input" in seen[0]  # the embed request shape, not chat's "messages"


async def test_test_model_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/providers/openai/test-model", json={"api_key": SECRET_KEY, "model": "m"})
    assert response.status_code == 401


async def test_test_model_requires_a_model(client: AsyncClient) -> None:
    headers = await _token(client, "testmodel-nomodel@example.com")
    for body in ({"api_key": SECRET_KEY}, {"api_key": SECRET_KEY, "model": ""}):
        response = await client.post("/providers/openai/test-model", headers=headers, json=body)
        assert response.status_code == 422


async def test_test_model_credential_shape_error(client: AsyncClient) -> None:
    headers = await _token(client, "testmodel-shape@example.com")
    response = await client.post("/providers/openai/test-model", headers=headers, json={"model": "gpt-4o"})
    assert response.status_code == 400


async def test_test_model_unknown_provider_is_404(client: AsyncClient) -> None:
    headers = await _token(client, "testmodel-unknown@example.com")
    response = await client.post("/providers/nope/test-model", headers=headers, json={"api_key": SECRET_KEY, "model": "m"})
    assert response.status_code == 404


async def test_test_model_unknown_model_is_a_specific_404(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_transport(monkeypatch, lambda r: httpx.Response(404, json={"error": {"message": "no such model"}}))
    headers = await _token(client, "testmodel-404@example.com")

    response = await client.post(
        "/providers/anthropic/test-model", headers=headers, json={"api_key": SECRET_KEY, "model": "claude-nope"}
    )

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "provider_model_not_found" and "claude-nope" in error["message"]


async def test_test_model_bad_key_is_401(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_transport(monkeypatch, lambda r: httpx.Response(401, json={}))
    headers = await _token(client, "testmodel-401@example.com")

    response = await client.post(
        "/providers/openai/test-model", headers=headers, json={"api_key": SECRET_KEY, "model": "gpt-4o"}
    )

    assert response.status_code == 401


async def test_test_model_timeout_is_502_provider_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    _use_transport(monkeypatch, handler)
    headers = await _token(client, "testmodel-timeout@example.com")

    response = await client.post(
        "/providers/openai/test-model", headers=headers, json={"api_key": SECRET_KEY, "model": "gpt-4o"}
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_unavailable"


async def test_test_model_is_rate_limited(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_transport(
        monkeypatch, lambda r: httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})
    )
    headers = await _token(client, "testmodel-ratelimit@example.com")

    statuses = [
        (
            await client.post(
                "/providers/openai/test-model", headers=headers, json={"api_key": SECRET_KEY, "model": "gpt-4o"}
            )
        ).status_code
        for _ in range(11)
    ]

    assert statuses[:10] == [200] * 10 and statuses[10] == 429


async def test_test_model_never_logs_or_returns_the_api_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect with {SECRET_KEY}", request=request)

    _use_transport(monkeypatch, handler)
    headers = await _token(client, "testmodel-nolog@example.com")

    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            "/providers/openai/test-model", headers=headers, json={"api_key": SECRET_KEY, "model": "gpt-4o"}
        )

    assert response.status_code == 502
    assert SECRET_KEY not in response.text
    assert SECRET_KEY not in caplog.text
