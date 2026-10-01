"""OllamaProvider tests — loopback validation and dynamic per-model
capability checks, against a mocked httpx transport (never a live local
Ollama instance in CI, per TESTING.md)."""

import json

import httpx
import pytest

from app.providers.errors import InvalidConfigError, NotSupportedError
from app.providers.ollama import OllamaProvider, validate_loopback_endpoint
from tests.providers.sample_schema import SampleClaim

VALID_CLAIM_JSON = json.dumps(
    {"claim_text": "x improves y", "page": 3, "confidence": 0.9, "source_excerpt": "x improves y by 10%"}
)


def _fail_if_called(request: httpx.Request) -> httpx.Response:  # pragma: no cover - assertion path
    raise AssertionError(f"no HTTP request should have been attempted, got {request.url}")


@pytest.mark.parametrize(
    "bad_endpoint",
    ["http://8.8.8.8:11434", "http://10.0.0.5:11434", "http://internal-ollama.corp:11434"],
)
def test_non_loopback_endpoint_rejected_before_any_request(bad_endpoint: str) -> None:
    with pytest.raises(InvalidConfigError):
        OllamaProvider(endpoint=bad_endpoint, transport=httpx.MockTransport(_fail_if_called))


@pytest.mark.parametrize("good_endpoint", ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"])
def test_loopback_endpoints_are_accepted(good_endpoint: str) -> None:
    assert validate_loopback_endpoint(good_endpoint) == good_endpoint


def _router_handler(capabilities: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/show":
            return httpx.Response(200, json={"capabilities": capabilities})
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.1"}, {"name": "nomic-embed-text"}]})
        if path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": VALID_CLAIM_JSON}}]})
        if path == "/v1/embeddings":
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        raise AssertionError(f"unexpected path {path}")

    return handler


async def test_generate_works_over_loopback_endpoint() -> None:
    provider = OllamaProvider(
        endpoint="http://127.0.0.1:11434", transport=httpx.MockTransport(_router_handler(["completion"]))
    )

    result = await provider.generate("extract the claim", SampleClaim, model="m")

    assert isinstance(result, SampleClaim)


async def test_embed_raises_not_supported_when_model_lacks_capability() -> None:
    provider = OllamaProvider(
        endpoint="http://127.0.0.1:11434", transport=httpx.MockTransport(_router_handler(["completion"]))
    )

    with pytest.raises(NotSupportedError):
        await provider.embed(["some text"], model="m")


async def test_embed_succeeds_when_model_reports_capability() -> None:
    provider = OllamaProvider(
        endpoint="http://127.0.0.1:11434",
        model="nomic-embed-text",
        transport=httpx.MockTransport(_router_handler(["completion", "embedding"])),
    )

    vectors = await provider.embed(["some text"], model="m")

    assert vectors == [[0.1, 0.2]]


async def test_vision_raises_not_supported_when_model_lacks_capability() -> None:
    provider = OllamaProvider(
        endpoint="http://127.0.0.1:11434", transport=httpx.MockTransport(_router_handler(["completion"]))
    )

    with pytest.raises(NotSupportedError):
        await provider.vision(b"fake-image-bytes", "describe this figure")


def test_available_models_queries_local_tags_endpoint() -> None:
    provider = OllamaProvider(
        endpoint="http://127.0.0.1:11434", transport=httpx.MockTransport(_router_handler(["completion"]))
    )

    models = provider.available_models()

    assert {m.id for m in models} == {"llama3.1", "nomic-embed-text"}


async def test_show_failure_does_not_leak_probed_response_body() -> None:
    """Regression for the security-review finding: a loopback-only endpoint
    is still a user-supplied address the request-issuing service doesn't
    control the content of — its response body must never be echoed back to
    the caller (SSRF-to-service-enumeration surface), only logged.
    """
    secret_body = "internal-service-banner: definitely-not-ollama v9.9.9"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=secret_body)

    provider = OllamaProvider(endpoint="http://127.0.0.1:11434", transport=httpx.MockTransport(handler))

    with pytest.raises(Exception) as exc_info:
        await provider.embed(["some text"], model="m")

    assert secret_body not in str(exc_info.value)


async def test_list_models_uses_async_tags_and_classifies() -> None:
    provider = OllamaProvider(
        endpoint="http://127.0.0.1:11434", transport=httpx.MockTransport(_router_handler(["completion"]))
    )

    models = await provider.list_models()

    assert {m.id: m.kind for m in models} == {"llama3.1": "chat", "nomic-embed-text": "embedding"}


async def test_list_models_unreachable_is_provider_unavailable() -> None:
    from app.providers.errors import ProviderUnavailableError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    provider = OllamaProvider(endpoint="http://127.0.0.1:11434", transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderUnavailableError):
        await provider.list_models()


async def test_ollama_does_not_send_json_mode() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": VALID_CLAIM_JSON}}]})

    provider = OllamaProvider(endpoint="http://127.0.0.1:11434", transport=httpx.MockTransport(handler))
    await provider.generate("extract", SampleClaim, model="m")

    assert "response_format" not in seen[0]
