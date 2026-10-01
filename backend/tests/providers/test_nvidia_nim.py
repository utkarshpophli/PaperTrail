"""NvidiaNimProvider tests against a mocked httpx transport — never a live
call to build.nvidia.com (TESTING.md)."""

import json

import httpx
import pytest

from app.providers.errors import AuthenticationError, InvalidConfigError, NotSupportedError
from app.providers.nvidia_nim import NvidiaNimProvider
from tests.providers.sample_schema import SampleClaim

VALID_CLAIM_JSON = json.dumps(
    {"claim_text": "x improves y", "page": 3, "confidence": 0.9, "source_excerpt": "x improves y by 10%"}
)


def _chat_response(content: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


def _provider(handler, *, model: str = "meta/llama-3.1-8b-instruct") -> NvidiaNimProvider:
    return NvidiaNimProvider(api_key="nvapi-test-key", model=model, transport=httpx.MockTransport(handler))


async def test_generate_returns_valid_data_matching_schema() -> None:
    provider = _provider(lambda request: _chat_response(VALID_CLAIM_JSON))

    result = await provider.generate("extract the claim", SampleClaim, model="m")

    assert isinstance(result, SampleClaim)
    assert result.page == 3


async def test_freeform_model_id_outside_shortlist_is_accepted() -> None:
    shortlisted_ids = {m.id for m in NvidiaNimProvider(api_key="x", transport=httpx.MockTransport(lambda r: _chat_response(""))).available_models()}
    freeform_model = "some-vendor/brand-new-model-not-in-shortlist"
    assert freeform_model not in shortlisted_ids

    provider = _provider(lambda request: _chat_response(VALID_CLAIM_JSON), model=freeform_model)

    result = await provider.generate("extract the claim", SampleClaim, model="m")

    assert isinstance(result, SampleClaim)


async def test_vision_raises_not_supported_error() -> None:
    provider = _provider(lambda request: _chat_response(VALID_CLAIM_JSON))

    with pytest.raises(NotSupportedError):
        await provider.vision(b"fake-image-bytes", "describe this figure")


async def test_embed_returns_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})

    provider = _provider(handler)

    vectors = await provider.embed(["some evidence text"], model="m")

    assert vectors == [[0.1, 0.2, 0.3]]


async def test_embed_request_includes_model_and_input_type() -> None:
    """Regression: NIM's retrieval embedders (nv-embedqa-*) require an
    input_type field the shared OpenAI-compatible adapter never sent --
    this was previously untested against anything but a mocked transport
    that didn't check the payload shape."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})

    provider = _provider(handler)

    await provider.embed(["text"], model="nvidia/nv-embedqa-e5-v5")

    assert seen[0]["model"] == "nvidia/nv-embedqa-e5-v5"
    assert seen[0]["input_type"] == "passage"
    assert seen[0]["truncate"] == "END"


async def test_stream_yields_text_deltas_via_sse() -> None:
    # Split so the accumulated text is valid JSON matching SampleClaim — this
    # test is about SSE chunk parsing, not the retry path (covered
    # separately in test_structured_output.py).
    half = len(VALID_CLAIM_JSON) // 2
    parts = [VALID_CLAIM_JSON[:half], VALID_CLAIM_JSON[half:]]

    def handler(request: httpx.Request) -> httpx.Response:
        lines = [f"data: {json.dumps({'choices': [{'delta': {'content': part}}]})}" for part in parts]
        lines.append("data: [DONE]")
        body = "\n\n".join(lines) + "\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    provider = _provider(handler)

    chunks = [chunk async for chunk in provider.stream("extract the claim", SampleClaim, model="m")]

    assert "".join(chunks) == VALID_CLAIM_JSON


async def test_auth_failure_maps_to_authentication_error() -> None:
    provider = _provider(lambda request: httpx.Response(401, json={"error": "invalid api key"}))

    with pytest.raises(AuthenticationError):
        await provider.generate("extract the claim", SampleClaim, model="m")


async def test_504_from_nims_own_gateway_is_retried_once_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test that NIM inherits OpenAICompatibleProvider's generalized
    retry (confirmed live: NIM's own gateway 504s a real extraction call
    after minutes of waiting, not instantly like a 429) -- full retry
    behavior is covered generically in test_openai_compatible_family.py."""

    async def _instant_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.providers.openai_compatible.asyncio.sleep", _instant_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(504, text="gateway timeout")
        return _chat_response(VALID_CLAIM_JSON)

    provider = _provider(handler)
    result = await provider.generate("extract the claim", SampleClaim, model="m")

    assert isinstance(result, SampleClaim)
    assert calls["n"] == 2


def test_available_models_returns_free_tier_shortlist() -> None:
    provider = _provider(lambda request: _chat_response(""))

    models = provider.available_models()

    assert len(models) > 0
    assert all(model.id and model.label for model in models)
    assert any("embed" in model.capabilities for model in models)


def test_missing_api_key_raises_invalid_config_error() -> None:
    with pytest.raises(InvalidConfigError):
        NvidiaNimProvider(api_key="")
