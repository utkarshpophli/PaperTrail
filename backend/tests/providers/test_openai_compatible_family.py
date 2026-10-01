"""Shared behaviour of every OpenAI-compatible adapter (OpenAI, OpenRouter,
NVIDIA NIM, LM Studio, llama.cpp), against a mocked httpx transport - never a
live call (TESTING.md)."""

import asyncio
import io
import json
from collections.abc import Callable

import httpx
import pytest
from PIL import Image

from app.providers.errors import (
    AuthenticationError,
    InvalidConfigError,
    NotSupportedError,
    OutputTruncatedError,
    ProviderUnavailableError,
    StructuredOutputError,
)
from app.providers.groq import GroqProvider
from app.providers.llama_cpp import LlamaCppProvider
from app.providers.lmstudio import LMStudioProvider
from app.providers.nvidia_nim import NvidiaNimProvider
from app.providers.openai import OpenAIProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.openrouter import OpenRouterProvider
from tests.providers.sample_schema import SampleClaim

VALID_CLAIM_JSON = json.dumps(
    {"claim_text": "x improves y", "page": 3, "confidence": 0.9, "source_excerpt": "x improves y by 10%"}
)
INVALID_CLAIM_JSON = json.dumps({"claim_text": "x improves y", "page": "not-a-number"})

Factory = Callable[[httpx.BaseTransport], OpenAICompatibleProvider]

FACTORIES: dict[str, Factory] = {
    "openai": lambda t: OpenAIProvider(api_key="sk-test-key", transport=t),
    "openrouter": lambda t: OpenRouterProvider(api_key="sk-or-test-key", transport=t),
    "groq": lambda t: GroqProvider(api_key="gsk-test-key", transport=t),
    "nvidia_nim": lambda t: NvidiaNimProvider(api_key="nvapi-test-key", transport=t),
    "lmstudio": lambda t: LMStudioProvider(endpoint="http://localhost:1234", transport=t),
    "llama_cpp": lambda t: LlamaCppProvider(endpoint="http://127.0.0.1:8080", transport=t),
}
JSON_MODE = {
    "openai": True,
    "openrouter": True,
    "groq": True,
    "nvidia_nim": True,
    "lmstudio": False,
    "llama_cpp": False,
}

every_provider = pytest.mark.parametrize("name", list(FACTORIES))


def _chat(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _make(name: str, handler: Callable[[httpx.Request], httpx.Response]) -> OpenAICompatibleProvider:
    return FACTORIES[name](httpx.MockTransport(handler))


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, format="PNG")
    return buf.getvalue()


async def _instant_sleep(_seconds: float) -> None:
    """Replaces the real 429-retry backoff so tests don't actually wait."""


def _recording_sleep(delays: list[float]) -> Callable[[float], object]:
    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    return sleep


@every_provider
async def test_generate_success_and_json_mode_flag(name: str) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _chat(VALID_CLAIM_JSON)

    result = await _make(name, handler).generate("extract", SampleClaim, model="m")

    assert isinstance(result, SampleClaim)
    assert ("response_format" in seen[0]) is JSON_MODE[name]


@every_provider
async def test_generate_retries_once_on_invalid_structured_output(name: str) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _chat(INVALID_CLAIM_JSON if calls["n"] == 1 else VALID_CLAIM_JSON)

    assert isinstance(await _make(name, handler).generate("extract", SampleClaim, model="m"), SampleClaim)
    assert calls["n"] == 2


@every_provider
async def test_second_invalid_output_surfaces(name: str) -> None:
    with pytest.raises(StructuredOutputError):
        await _make(name, lambda r: _chat(INVALID_CLAIM_JSON)).generate("extract", SampleClaim, model="m")


@every_provider
async def test_401_maps_to_authentication_error(name: str) -> None:
    with pytest.raises(AuthenticationError):
        await _make(name, lambda r: httpx.Response(401, json={"error": "nope"})).generate("x", SampleClaim, model="m")


@every_provider
async def test_429_maps_to_provider_unavailable(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _instant_sleep)
    with pytest.raises(ProviderUnavailableError, match="Rate limit"):
        await _make(name, lambda r: httpx.Response(429, text="slow down")).generate("x", SampleClaim, model="m")


@every_provider
async def test_429_is_retried_then_succeeds(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _instant_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="slow down")
        return _chat(VALID_CLAIM_JSON)

    assert isinstance(await _make(name, handler).generate("extract", SampleClaim, model="m"), SampleClaim)
    assert calls["n"] == 2


@every_provider
async def test_429_retry_honours_retry_after_header(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _recording_sleep(delays))
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")
        return _chat(VALID_CLAIM_JSON)

    await _make(name, handler).generate("extract", SampleClaim, model="m")
    assert delays == [7.0]


@every_provider
async def test_timeout_is_retried_then_raises_provider_unavailable(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _instant_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("read timed out", request=request)

    with pytest.raises(ProviderUnavailableError, match="timed out"):
        await _make(name, handler).generate("x", SampleClaim, model="m")
    assert calls["n"] == 4  # _MAX_ATTEMPTS, then give up


@every_provider
async def test_timeout_is_retried_then_succeeds(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _instant_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("read timed out", request=request)
        return _chat(VALID_CLAIM_JSON)

    assert isinstance(await _make(name, handler).generate("extract", SampleClaim, model="m"), SampleClaim)
    assert calls["n"] == 2


@every_provider
async def test_stream_timeout_maps_to_provider_unavailable(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _instant_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    with pytest.raises(ProviderUnavailableError, match="timed out"):
        _ = [chunk async for chunk in _make(name, handler).stream("x", SampleClaim, model="m")]


@every_provider
async def test_stream_connection_error_maps_to_provider_unavailable(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _instant_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderUnavailableError):
        _ = [chunk async for chunk in _make(name, handler).stream("x", SampleClaim, model="m")]


@every_provider
@pytest.mark.parametrize("status", [502, 503, 504])
async def test_5xx_is_retried_then_succeeds(name: str, status: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _instant_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(status, text="upstream had a bad moment")
        return _chat(VALID_CLAIM_JSON)

    assert isinstance(await _make(name, handler).generate("extract", SampleClaim, model="m"), SampleClaim)
    assert calls["n"] == 2


@every_provider
async def test_5xx_that_never_recovers_exhausts_the_retry_cap(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bounded: _MAX_ATTEMPTS (4) total, then a clear ProviderUnavailableError."""
    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _instant_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="still down")

    with pytest.raises(ProviderUnavailableError):
        await _make(name, handler).generate("x", SampleClaim, model="m")
    assert calls["n"] == 4


@every_provider
@pytest.mark.parametrize("status", [404, 401])
async def test_permanent_failure_is_never_retried(name: str, status: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: 404 (unknown model) and 401 (bad key) are permanent
    -- retrying wastes time against a credential/id that won't fix itself."""
    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _instant_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status, text="nope")

    expected = AuthenticationError if status == 401 else ProviderUnavailableError
    with pytest.raises(expected):
        await _make(name, handler).generate("x", SampleClaim, model="m")
    assert calls["n"] == 1


@every_provider
async def test_falls_back_to_reasoning_content_when_content_is_null(name: str) -> None:
    """Confirmed live against NIM-hosted reasoning models (deepseek-ai/
    deepseek-v4.1-flash, z-ai/glm-5.3-flash): a normal finish_reason="stop"
    completion can still leave the standard `content` field null, with the
    real answer in the non-standard `reasoning_content` field instead. This
    used to silently become "" and fail JSON parsing on data that was in the
    response the whole time."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": None, "reasoning_content": VALID_CLAIM_JSON}}]},
        )

    result = await _make(name, handler).generate("x", SampleClaim, model="m")
    assert isinstance(result, SampleClaim)


@every_provider
async def test_prefers_content_over_reasoning_content_when_both_present(name: str) -> None:
    other_claim = json.dumps(
        {"claim_text": "different", "page": 1, "confidence": 0.1, "source_excerpt": "different"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": VALID_CLAIM_JSON, "reasoning_content": other_claim}}]},
        )

    result = await _make(name, handler).generate("x", SampleClaim, model="m")
    assert result.page == 3  # from VALID_CLAIM_JSON, not the reasoning_content fallback


def _sse(*deltas: dict, finish_reason: str | None = "stop") -> httpx.Response:
    events = [{"choices": [{"delta": d, "finish_reason": None}]} for d in deltas]
    events.append({"choices": [{"delta": {}, "finish_reason": finish_reason}]})
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


@every_provider
async def test_generate_sends_stream_true_and_accumulates_sse(name: str) -> None:
    """NIM's gateway 504s non-streamed requests at ~300s; generate() streams
    on the wire and reassembles the answer."""
    half = len(VALID_CLAIM_JSON) // 2
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return _sse(
            {"reasoning_content": "thinking {not json"},
            {"content": VALID_CLAIM_JSON[:half]},
            {"content": VALID_CLAIM_JSON[half:]},
        )

    result = await _make(name, handler).generate("x", SampleClaim, model="m")
    assert result.page == 3
    assert sent[0]["stream"] is True


@every_provider
async def test_sse_reasoning_fallback_only_when_no_content(name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _sse({"reasoning_content": VALID_CLAIM_JSON})

    result = await _make(name, handler).generate("x", SampleClaim, model="m")
    assert result.page == 3


@every_provider
@pytest.mark.parametrize("delta", [{"reasoning_content": "still thinking"}, {"content": '{"claim_text": "x'}])
async def test_finish_reason_length_raises_truncated_without_repair_retry(name: str, delta: dict) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _sse(delta, finish_reason="length")

    with pytest.raises(OutputTruncatedError):
        await _make(name, handler).generate("x", SampleClaim, model="m")
    assert calls["n"] == 1


@every_provider
async def test_stream_never_splices_reasoning_into_output(name: str) -> None:
    half = len(VALID_CLAIM_JSON) // 2

    def handler(request: httpx.Request) -> httpx.Response:
        return _sse(
            {"reasoning_content": "chain of thought"},
            {"content": VALID_CLAIM_JSON[:half]},
            {"content": VALID_CLAIM_JSON[half:]},
        )

    chunks = [c async for c in _make(name, handler).stream("x", SampleClaim, model="m")]
    assert "".join(chunks) == VALID_CLAIM_JSON


@every_provider
async def test_stream_yields_reasoning_answer_when_content_empty(name: str) -> None:
    half = len(VALID_CLAIM_JSON) // 2

    def handler(request: httpx.Request) -> httpx.Response:
        return _sse({"reasoning_content": VALID_CLAIM_JSON[:half]}, {"reasoning_content": VALID_CLAIM_JSON[half:]})

    chunks = [c async for c in _make(name, handler).stream("x", SampleClaim, model="m")]
    assert chunks == [VALID_CLAIM_JSON]


@every_provider
async def test_unexpected_response_shape_does_not_echo_body(name: str) -> None:
    secret = "upstream-secret-body-content"
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await _make(name, lambda r: httpx.Response(200, json={"weird": secret})).generate("x", SampleClaim, model="m")
    assert secret not in str(exc_info.value)


@every_provider
async def test_error_body_is_not_echoed(name: str) -> None:
    secret = "internal-banner-9.9.9"
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await _make(name, lambda r: httpx.Response(500, text=secret)).generate("x", SampleClaim, model="m")
    assert secret not in str(exc_info.value)


@pytest.mark.parametrize(
    ("name", "supports"),
    [("openai", True), ("openrouter", False), ("nvidia_nim", True), ("lmstudio", True), ("llama_cpp", False)],
)
async def test_embed_capability_is_explicit(name: str, supports: bool) -> None:
    provider = _make(name, lambda r: httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]}))
    if supports:
        assert await provider.embed(["t"], model="m") == [[0.1, 0.2]]
    else:
        with pytest.raises(NotSupportedError):
            await provider.embed(["t"], model="m")


@pytest.mark.parametrize(
    ("name", "supports"),
    [("openai", True), ("openrouter", True), ("nvidia_nim", False), ("lmstudio", True), ("llama_cpp", False)],
)
async def test_vision_capability_is_explicit(name: str, supports: bool) -> None:
    provider = _make(name, lambda r: _chat("a figure"))
    if supports:
        assert await provider.vision(_png(), "describe") == "a figure"
    else:
        with pytest.raises(NotSupportedError):
            await provider.vision(_png(), "describe")


@pytest.mark.parametrize("ctor", [OpenAIProvider, OpenRouterProvider, NvidiaNimProvider])
def test_cloud_providers_reject_missing_key(ctor: type) -> None:
    with pytest.raises(InvalidConfigError):
        ctor(api_key="")


@pytest.mark.parametrize(
    ("name", "url"),
    [
        ("openai", "https://api.openai.com/v1/chat/completions"),
        ("openrouter", "https://openrouter.ai/api/v1/chat/completions"),
        ("nvidia_nim", "https://integrate.api.nvidia.com/v1/chat/completions"),
        ("lmstudio", "http://localhost:1234/v1/chat/completions"),
        ("llama_cpp", "http://127.0.0.1:8080/v1/chat/completions"),
    ],
)
async def test_requests_go_to_the_fixed_host(name: str, url: str) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return _chat(VALID_CLAIM_JSON)

    await _make(name, handler).generate("x", SampleClaim, model="m")
    assert seen == [url]


@pytest.mark.parametrize("name", ["openai", "openrouter", "nvidia_nim"])
async def test_api_key_sent_as_bearer(name: str) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return _chat(VALID_CLAIM_JSON)

    await _make(name, handler).generate("x", SampleClaim, model="m")
    assert seen[0].startswith("Bearer ")


@pytest.mark.parametrize("name", ["lmstudio", "llama_cpp"])
async def test_local_providers_send_no_authorization(name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return _chat(VALID_CLAIM_JSON)

    await _make(name, handler).generate("x", SampleClaim, model="m")


# --- timeout wiring -------------------------------------------------------


def test_default_timeout_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Settings:
        provider_read_timeout_seconds = 123.0

    monkeypatch.setattr("app.providers.timeouts.get_settings", lambda: _Settings())

    assert OpenAIProvider(api_key="sk-test-key")._timeout == httpx.Timeout(connect=10, read=123.0, write=30, pool=10)


def test_default_read_timeout_is_600_seconds() -> None:
    timeout = OpenAIProvider(api_key="sk-test-key")._timeout
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (10, 600.0, 30, 10)


def test_constructor_timeout_override_wins() -> None:
    provider = OpenAICompatibleProvider(base_url="https://x.test/v1", model="m", timeout=7.0)
    assert provider._timeout == httpx.Timeout(7.0)


async def test_configured_timeout_reaches_the_httpx_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    real_client = httpx.AsyncClient

    def spy(*args: object, **kwargs: object) -> httpx.AsyncClient:
        captured.append(kwargs.get("timeout"))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.providers.openai_compatible.httpx.AsyncClient", spy)

    await _make("nvidia_nim", lambda r: _chat(VALID_CLAIM_JSON)).generate("x", SampleClaim, model="m")

    assert captured == [httpx.Timeout(connect=10, read=600.0, write=30, pool=10)]


# --- list_models ----------------------------------------------------------


async def test_openai_style_listing_parses_and_classifies() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.path == "/v1/models"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-4o"},
                    {"id": "text-embedding-3-small"},
                    {"id": "whisper-1"},
                    {"id": "dall-e-3"},
                    {"id": "omni-moderation-latest"},
                    {"id": "gpt-4o-mini-tts"},
                    {"id": "gpt-4o-realtime-preview"},
                    {"weird": "no id"},
                ]
            },
        )

    models = await _make("openai", handler).list_models()

    assert {m.id: m.kind for m in models} == {
        "gpt-4o": "chat",
        "text-embedding-3-small": "embedding",
        "whisper-1": "other",
        "dall-e-3": "other",
        "omni-moderation-latest": "other",
        "gpt-4o-mini-tts": "other",
        "gpt-4o-realtime-preview": "other",
    }


async def test_openrouter_listing_uses_name_and_context_length() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://openrouter.ai/api/v1/models"
        return httpx.Response(
            200, json={"data": [{"id": "openai/gpt-4o", "name": "OpenAI: GPT-4o", "context_length": 128000}]}
        )

    [model] = await _make("openrouter", handler).list_models()

    assert (model.id, model.label, model.context_length, model.kind) == (
        "openai/gpt-4o",
        "OpenAI: GPT-4o",
        128000,
        "chat",
    )


async def test_nim_listing_filters_non_chat_kinds() -> None:
    payload = {
        "data": [
            {"id": "meta/llama-3.1-8b-instruct"},
            {"id": "nvidia/nv-embedqa-e5-v5"},
            {"id": "nvidia/nv-rerankqa-mistral-4b-v3"},
            {"id": "nvidia/nemoretriever-parse"},
            {"id": "nvidia/llama-3.1-nemoguard-8b-content-safety"},
            {"id": "baai/bge-m3"},
        ]
    }
    models = await _make("nvidia_nim", lambda r: httpx.Response(200, json=payload)).list_models()

    assert [m.id for m in models if m.kind == "chat"] == ["meta/llama-3.1-8b-instruct"]


@pytest.mark.parametrize("name", ["lmstudio", "llama_cpp"])
async def test_local_listing_hits_v1_models(name: str) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": "qwen2.5-7b-instruct"}]})

    models = await _make(name, handler).list_models()

    assert seen == ["/v1/models"] and [m.id for m in models] == ["qwen2.5-7b-instruct"]


@every_provider
async def test_listing_401_is_authentication_error(name: str) -> None:
    with pytest.raises(AuthenticationError):
        await _make(name, lambda r: httpx.Response(401, json={})).list_models()


@every_provider
async def test_listing_timeout_maps_to_provider_unavailable(name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("t", request=request)

    with pytest.raises(ProviderUnavailableError):
        await _make(name, handler).list_models()


async def test_listing_bad_shape_is_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError):
        await _make("openai", lambda r: httpx.Response(200, json={"models": []})).list_models()


# --- Operation deadline (docs/NIM_HANG_FIX.md) -------------------------------
#
# A gateway that keeps a connection alive with intermittent traffic can reset
# HTTPX's read timeout indefinitely without ever completing a usable response
# (confirmed live against NVIDIA NIM: a 33+ minute hang with no success,
# error, or retry). These tests exercise the wall-clock operation deadline
# directly on the base class -- it's not exposed as a constructor kwarg on
# any concrete subclass (none need to override it outside tests), and the
# behavior lives entirely in OpenAICompatibleProvider, so testing it once
# here covers every subclass.


async def _never_responds(request: httpx.Request) -> httpx.Response:
    await asyncio.Event().wait()
    raise AssertionError("unreachable")  # pragma: no cover


def _deadlined_provider(handler: Callable, operation_timeout: float) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="https://example.test",
        model="m",
        transport=httpx.MockTransport(handler),
        operation_timeout=operation_timeout,
    )


async def test_operation_deadline_times_out_generate() -> None:
    provider = _deadlined_provider(_never_responds, operation_timeout=0.05)
    with pytest.raises(ProviderUnavailableError, match="did not complete within"):
        await provider.generate("x", SampleClaim, model="m")


async def test_operation_deadline_times_out_embed() -> None:
    provider = _deadlined_provider(_never_responds, operation_timeout=0.05)
    with pytest.raises(ProviderUnavailableError, match="did not complete within"):
        await provider.embed(["x"], model="m")


async def test_operation_deadline_times_out_a_stalled_stream() -> None:
    provider = _deadlined_provider(_never_responds, operation_timeout=0.05)
    with pytest.raises(ProviderUnavailableError, match="did not complete within"):
        _ = [chunk async for chunk in provider.stream("x", SampleClaim, model="m")]


async def test_operation_deadline_error_never_carries_a_body_or_key() -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://example.test",
        model="m",
        api_key="sk-super-secret",
        transport=httpx.MockTransport(_never_responds),
        operation_timeout=0.05,
    )
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await provider.generate("x", SampleClaim, model="m")
    assert "sk-super-secret" not in str(exc_info.value)


async def test_caller_cancellation_propagates_and_is_not_converted_to_provider_error() -> None:
    started = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    provider = _deadlined_provider(handler, operation_timeout=60.0)
    task = asyncio.ensure_future(provider.generate("x", SampleClaim, model="m"))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_operation_deadline_does_not_interfere_with_a_normal_fast_request() -> None:
    provider = _deadlined_provider(lambda r: _chat(VALID_CLAIM_JSON), operation_timeout=5.0)
    result = await provider.generate("extract", SampleClaim, model="m")
    assert isinstance(result, SampleClaim)


async def test_operation_deadline_is_shared_across_the_schema_repair_attempt_not_reset() -> None:
    """The one structured-output repair attempt (structured_output.py) must
    share the original operation budget, not get a fresh deadline of its
    own -- otherwise two full-length attempts could each consume the whole
    timeout, doubling the effective wait."""
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _chat(INVALID_CLAIM_JSON)  # triggers the one repair retry
        await asyncio.sleep(0.2)  # slower than the remaining shared budget
        return _chat(VALID_CLAIM_JSON)

    provider = _deadlined_provider(handler, operation_timeout=0.1)
    with pytest.raises(ProviderUnavailableError, match="did not complete within"):
        await provider.generate("extract", SampleClaim, model="m")
    assert calls["n"] == 2  # the repair attempt did start, but the shared deadline still cut it off
