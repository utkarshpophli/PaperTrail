"""AnthropicProvider tests against a mocked httpx transport - never a live call."""

import io
import json

import httpx
import pytest
from PIL import Image

from app.providers.anthropic import AnthropicProvider
from app.providers.errors import (
    AuthenticationError,
    InvalidConfigError,
    ModelNotFoundError,
    NotSupportedError,
    OutputTruncatedError,
    ProviderUnavailableError,
    StructuredOutputError,
)
from tests.providers.sample_schema import SampleClaim

VALID_CLAIM_JSON = json.dumps(
    {"claim_text": "x improves y", "page": 3, "confidence": 0.9, "source_excerpt": "x improves y by 10%"}
)
INVALID_CLAIM_JSON = json.dumps({"claim_text": "x improves y", "page": "not-a-number"})


def _message(text: str) -> httpx.Response:
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"})


def _provider(handler) -> AnthropicProvider:
    return AnthropicProvider(api_key="sk-ant-test-key", transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _instant_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.providers.retry.asyncio.sleep", _no_wait)
    monkeypatch.setattr("app.providers.anthropic.asyncio.sleep", _no_wait)


def _sse(*texts: str, stop_reason: str = "end_turn") -> httpx.Response:
    events = [{"type": "message_start"}]
    events += [{"type": "content_block_delta", "delta": {"type": "text_delta", "text": t}} for t in texts]
    events.append({"type": "message_delta", "delta": {"stop_reason": stop_reason}})
    events.append({"type": "message_stop"})
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)


async def test_generate_sends_required_headers_and_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _message(VALID_CLAIM_JSON)

    result = await _provider(handler).generate("extract the claim", SampleClaim, model="m")

    assert isinstance(result, SampleClaim) and result.page == 3
    request = seen[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant-test-key"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in request.headers
    assert body["max_tokens"] == 64000
    assert body["model"] == "m"
    assert body["messages"] == [{"role": "user", "content": "extract the claim"}]
    assert "claim_text" in body["system"]  # schema instruction is the system prompt, not the user turn


async def test_opts_override_model_and_max_tokens() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _message(VALID_CLAIM_JSON)

    await _provider(handler).generate("x", SampleClaim, model="claude-haiku-4-5", max_tokens=1024)

    assert seen[0]["model"] == "claude-haiku-4-5" and seen[0]["max_tokens"] == 1024


async def test_generate_retries_once_on_invalid_output() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _message(INVALID_CLAIM_JSON if calls["n"] == 1 else VALID_CLAIM_JSON)

    assert isinstance(await _provider(handler).generate("x", SampleClaim, model="m"), SampleClaim)
    assert calls["n"] == 2


async def test_second_invalid_output_raises_structured_output_error() -> None:
    with pytest.raises(StructuredOutputError):
        await _provider(lambda r: _message(INVALID_CLAIM_JSON)).generate("x", SampleClaim, model="m")


async def test_401_maps_to_authentication_error() -> None:
    with pytest.raises(AuthenticationError):
        await _provider(lambda r: httpx.Response(401, json={"error": {"type": "authentication_error"}})).generate(
            "x", SampleClaim, model="m"
        )


@pytest.mark.parametrize("status", [429, 500, 529])
async def test_rate_limit_and_server_errors_map_to_provider_unavailable(status: int) -> None:
    with pytest.raises(ProviderUnavailableError):
        await _provider(lambda r: httpx.Response(status, text="boom")).generate("x", SampleClaim, model="m")


async def test_404_is_a_specific_model_not_found_error() -> None:
    with pytest.raises(ModelNotFoundError, match="claude-nope"):
        await _provider(lambda r: httpx.Response(404, json={})).generate("x", SampleClaim, model="claude-nope")


async def test_timeout_maps_to_provider_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderUnavailableError, match="timed out"):
        await _provider(handler).generate("x", SampleClaim, model="m")


async def test_stream_timeout_maps_to_provider_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderUnavailableError, match="timed out"):
        _ = [c async for c in _provider(handler).stream("x", SampleClaim, model="m")]


async def test_upstream_error_body_is_not_echoed() -> None:
    secret = "credit balance banner 123"
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await _provider(lambda r: httpx.Response(400, json={"error": {"message": secret}})).generate("x", SampleClaim, model="m")
    assert secret not in str(exc_info.value)


async def test_stream_yields_text_deltas() -> None:
    half = len(VALID_CLAIM_JSON) // 2
    parts = [VALID_CLAIM_JSON[:half], VALID_CLAIM_JSON[half:]]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        events = [{"type": "message_start"}]
        events += [{"type": "content_block_delta", "delta": {"type": "text_delta", "text": p}} for p in parts]
        events.append({"type": "message_stop"})
        body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    chunks = [c async for c in _provider(handler).stream("x", SampleClaim, model="m")]

    assert "".join(chunks) == VALID_CLAIM_JSON


async def test_embed_is_not_supported() -> None:
    with pytest.raises(NotSupportedError):
        await _provider(lambda r: _message("")).embed(["t"], model="m")


async def test_vision_sends_base64_image_block() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, format="PNG")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _message("a figure")

    assert await _provider(handler).vision(buf.getvalue(), "describe") == "a figure"
    block = seen[0]["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/png"


async def test_vision_rejects_non_image_bytes() -> None:
    with pytest.raises(NotSupportedError):
        await _provider(lambda r: _message("")).vision(b"not an image", "describe")


def test_missing_api_key_raises_invalid_config() -> None:
    with pytest.raises(InvalidConfigError):
        AnthropicProvider(api_key="")


def test_available_models_is_a_static_fallback_list() -> None:
    models = _provider(lambda r: _message("")).available_models()
    assert models and all("generate" in m.capabilities for m in models)


def test_timeout_comes_from_settings_by_default() -> None:
    timeout = AnthropicProvider(api_key="sk-ant-test-key")._timeout
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (10, 600.0, 30, 10)


# --- list_models ----------------------------------------------------------


async def test_list_models_parses_display_names() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.path == "/v1/models"
        assert request.headers["x-api-key"] == "sk-ant-test-key"
        return httpx.Response(
            200,
            json={
                "data": [{"id": "claude-opus-4-1", "display_name": "Claude Opus 4.1", "type": "model"}],
                "has_more": False,
                "last_id": "claude-opus-4-1",
            },
        )

    [model] = await _provider(handler).list_models()

    assert (model.id, model.label, model.kind) == ("claude-opus-4-1", "Claude Opus 4.1", "chat")


async def test_list_models_follows_pagination() -> None:
    pages = {
        None: {"data": [{"id": "claude-a", "display_name": "A"}], "has_more": True, "last_id": "claude-a"},
        "claude-a": {"data": [{"id": "claude-b", "display_name": "B"}], "has_more": False, "last_id": "claude-b"},
    }
    seen_cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("after_id")
        seen_cursors.append(cursor)
        return httpx.Response(200, json=pages[cursor])

    models = await _provider(handler).list_models()

    assert [m.id for m in models] == ["claude-a", "claude-b"]
    assert seen_cursors == [None, "claude-a"]


async def test_list_models_pagination_is_capped() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200, json={"data": [{"id": f"claude-{calls['n']}"}], "has_more": True, "last_id": f"claude-{calls['n']}"}
        )

    models = await _provider(handler).list_models()

    assert calls["n"] == 5 and len(models) == 5


async def test_list_models_401_is_authentication_error() -> None:
    with pytest.raises(AuthenticationError):
        await _provider(lambda r: httpx.Response(401, json={})).list_models()


async def test_list_models_timeout_maps_to_provider_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("t", request=request)

    with pytest.raises(ProviderUnavailableError):
        await _provider(handler).list_models()


async def test_generate_streams_on_the_wire_and_reassembles() -> None:
    sent: list[dict] = []
    half = len(VALID_CLAIM_JSON) // 2

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return _sse(VALID_CLAIM_JSON[:half], VALID_CLAIM_JSON[half:])

    result = await _provider(handler).generate("x", SampleClaim, model="claude-opus-5-5")

    assert result.page == 3
    assert sent[0]["stream"] is True


async def test_max_tokens_stop_raises_truncated_without_repair_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _sse('{"claim_text": "x', stop_reason="max_tokens")

    with pytest.raises(OutputTruncatedError, match="max_tokens"):
        await _provider(handler).generate("x", SampleClaim, model="m")
    assert calls["n"] == 1


async def test_refusal_stop_is_a_clear_error() -> None:
    with pytest.raises(ProviderUnavailableError, match="refusal"):
        await _provider(lambda r: _sse("", stop_reason="refusal")).generate("x", SampleClaim, model="m")


@pytest.mark.parametrize("status", [429, 529])
async def test_overload_and_rate_limit_are_retried_then_succeed(status: int) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status, text="busy") if calls["n"] == 1 else _sse(VALID_CLAIM_JSON)

    assert (await _provider(handler).generate("x", SampleClaim, model="m")).page == 3
    assert calls["n"] == 2


async def test_operation_deadline_bounds_a_stalled_request() -> None:
    async def never(request: httpx.Request) -> httpx.Response:
        import asyncio

        await asyncio.Event().wait()  # never set (asyncio.sleep is patched to instant here)
        raise AssertionError("unreachable")

    provider = AnthropicProvider(api_key="k", operation_timeout=0.05, transport=httpx.MockTransport(never))
    with pytest.raises(ProviderUnavailableError, match="did not complete within"):
        await provider.generate("x", SampleClaim, model="m")


def test_known_models_are_current() -> None:
    ids = [m.id for m in _provider(lambda r: httpx.Response(200)).available_models()]
    assert ids == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5"]
