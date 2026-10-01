"""GeminiProvider tests against a mocked httpx transport injected into the
google-genai SDK's client — never a live call to Google's API (TESTING.md).
"""

import json
from typing import Annotated, Literal, Union

import httpx
import pytest
from google.genai import types as genai_types
from pydantic import BaseModel, Field

from app.providers.errors import AuthenticationError, StructuredOutputError
from app.providers.gemini import GeminiProvider
from tests.providers.sample_schema import SampleClaim

VALID_CLAIM_JSON = json.dumps(
    {"claim_text": "x improves y", "page": 3, "confidence": 0.9, "source_excerpt": "x improves y by 10%"}
)
INVALID_CLAIM_JSON = json.dumps({"claim_text": "x improves y", "page": "not-a-number"})


def _candidate_response(text: str, status: int = 200) -> httpx.Response:
    body = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    return httpx.Response(status, json=body)


def _provider(handler) -> GeminiProvider:
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiProvider(api_key="test-key", http_options=genai_types.HttpOptions(httpx_async_client=mock_client))


class _CatVariant(BaseModel):
    type: Literal["cat"] = "cat"
    meow: str


class _DogVariant(BaseModel):
    type: Literal["dog"] = "dog"
    bark: str


class _Pet(BaseModel):
    pet: Annotated[Union[_CatVariant, _DogVariant], Field(discriminator="type")]


async def test_generate_supports_discriminated_union_schemas() -> None:
    """Google's genai Schema type has no discriminator/oneOf fields, only
    anyOf -- a Pydantic discriminated union (like StorySpecOutput's
    11-variant visual field) must not crash schema construction. Regression
    for a live bug: passing the schema straight to response_schema made the
    SDK raise pydantic_core.ValidationError('extra_forbidden') while
    building the request, before any HTTP call was even made."""
    payload = json.dumps({"pet": {"type": "dog", "bark": "woof"}})
    provider = _provider(lambda request: _candidate_response(payload))

    result = await provider.generate("pick a pet", _Pet, model="m")

    assert isinstance(result, _Pet)
    assert result.pet.type == "dog"


async def test_generate_falls_back_to_prompt_json_when_schema_too_complex() -> None:
    """Regression for a live bug: Gemini's constrained decoding has a real
    complexity ceiling (confirmed against the real API with
    StorySpecOutput's 11-variant visual union nested in a list of
    sections) -- it rejects an overly complex response_schema with a 400
    naming no field, just "too many states for serving". The first request
    must retry once without response_schema (schema embedded in the prompt
    instead), not surface the 400 to the caller."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "responseSchema" in body.get("generationConfig", {}):
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": "The specified schema produces a constraint that has too many states for serving.",
                        "status": "INVALID_ARGUMENT",
                    }
                },
            )
        return _candidate_response(VALID_CLAIM_JSON)

    provider = _provider(handler)

    result = await provider.generate("extract the claim", SampleClaim, model="m")

    assert isinstance(result, SampleClaim)
    assert len(calls) == 2
    assert "responseSchema" in calls[0]["generationConfig"]
    assert "responseSchema" not in calls[1]["generationConfig"]


async def test_generate_returns_valid_data_matching_schema() -> None:
    provider = _provider(lambda request: _candidate_response(VALID_CLAIM_JSON))

    result = await provider.generate("extract the claim", SampleClaim, model="m")

    assert isinstance(result, SampleClaim)
    assert result.page == 3
    assert result.confidence == 0.9


async def test_generate_retries_once_then_succeeds_on_invalid_first_response() -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return _candidate_response(INVALID_CLAIM_JSON if call_count["n"] == 1 else VALID_CLAIM_JSON)

    provider = _provider(handler)

    result = await provider.generate("extract the claim", SampleClaim, model="m")

    assert isinstance(result, SampleClaim)
    assert call_count["n"] == 2


async def test_generate_raises_structured_output_error_after_two_invalid_responses() -> None:
    provider = _provider(lambda request: _candidate_response(INVALID_CLAIM_JSON))

    with pytest.raises(StructuredOutputError):
        await provider.generate("extract the claim", SampleClaim, model="m")


async def test_generate_maps_auth_failure_to_authentication_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": 401, "message": "API key not valid", "status": "UNAUTHENTICATED"}})

    provider = _provider(handler)

    with pytest.raises(AuthenticationError):
        await provider.generate("extract the claim", SampleClaim, model="m")


async def test_generate_maps_invalid_api_key_to_authentication_error() -> None:
    """Regression: Google's real API returns HTTP 400 (not 401/403) for an
    invalid API key, with the actual signal in a structured reason code —
    this exact response body was captured from a live call with a bad key,
    not guessed. Before this fix, it fell through to a generic
    ProviderUnavailableError, which fails AI_PROVIDERS.md's requirement that
    a user can tell auth failure from a generic unavailable provider."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": 400,
                    "message": "API key not valid. Please pass a valid API key.",
                    "status": "INVALID_ARGUMENT",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": "API_KEY_INVALID",
                            "domain": "googleapis.com",
                        }
                    ],
                }
            },
        )

    provider = _provider(handler)

    with pytest.raises(AuthenticationError):
        await provider.generate("extract the claim", SampleClaim, model="m")


async def test_stream_yields_text_deltas() -> None:
    # Split so the accumulated text is valid JSON matching SampleClaim — this
    # test is about chunk delivery, not the retry path (covered separately).
    half = len(VALID_CLAIM_JSON) // 2
    parts = [VALID_CLAIM_JSON[:half], VALID_CLAIM_JSON[half:]]
    lines = []
    for part in parts:
        lines.append("data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": part}]}}]}))
        lines.append("")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="\n".join(lines))

    provider = _provider(handler)

    chunks = [chunk async for chunk in provider.stream("say hi", SampleClaim, model="m")]

    assert "".join(chunks) == VALID_CLAIM_JSON


def test_available_models_returns_real_shaped_data() -> None:
    provider = _provider(lambda request: _candidate_response(VALID_CLAIM_JSON))

    models = provider.available_models()

    assert len(models) > 0
    assert all(model.id and model.label and model.capabilities for model in models)
    assert any("generate" in model.capabilities for model in models)
    assert any("embed" in model.capabilities for model in models)


# --- list_models / timeout -------------------------------------------------


async def test_list_models_strips_prefix_and_classifies_by_supported_actions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-2.5-flash",
                        "displayName": "Gemini 2.5 Flash",
                        "inputTokenLimit": 1048576,
                        "supportedGenerationMethods": ["generateContent", "countTokens"],
                    },
                    {"name": "models/text-x", "displayName": "X", "supportedGenerationMethods": ["embedContent"]},
                    {"name": "models/aqa", "displayName": "AQA", "supportedGenerationMethods": ["generateAnswer"]},
                    {
                        "name": "models/gemini-2.5-flash-image",
                        "displayName": "Flash Image",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                ]
            },
        )

    models = await _provider(handler).list_models()

    by_id = {m.id: m for m in models}
    assert by_id["gemini-2.5-flash"].kind == "chat"
    assert by_id["gemini-2.5-flash"].label == "Gemini 2.5 Flash"
    assert by_id["gemini-2.5-flash"].context_length == 1048576
    assert by_id["text-x"].kind == "embedding"
    assert by_id["aqa"].kind == "other"
    assert by_id["gemini-2.5-flash-image"].kind == "other"


async def test_list_models_bad_key_maps_to_authentication_error() -> None:
    body = {"error": {"code": 400, "message": "API key not valid", "details": [{"reason": "API_KEY_INVALID"}]}}
    with pytest.raises(AuthenticationError):
        await _provider(lambda r: httpx.Response(400, json=body)).list_models()


async def test_list_models_timeout_maps_to_provider_unavailable() -> None:
    from app.providers.errors import ProviderUnavailableError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderUnavailableError):
        await _provider(handler).list_models()


async def test_upstream_error_body_never_reaches_the_raised_exception(caplog: pytest.LogCaptureFixture) -> None:
    """Security regression: Gemini's raw error text (``exc.message``) must
    never be echoed into a client-visible exception message — it belongs in
    the server log only, same discipline as every other provider adapter
    (SECURITY.md: never echo an upstream response body back to the caller).
    """
    secret_marker = "quota-project-billing-account-12345-do-not-leak"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"error": {"code": 500, "message": f"internal error, details: {secret_marker}", "status": "INTERNAL"}},
        )

    provider = _provider(handler)

    with caplog.at_level("WARNING"):
        with pytest.raises(Exception) as exc_info:
            await provider.generate("extract the claim", SampleClaim, model="m")

    assert secret_marker not in str(exc_info.value)
    assert secret_marker not in (exc_info.value.args[0] if exc_info.value.args else "")
    assert any(secret_marker in record.message for record in caplog.records)


def test_default_request_timeout_is_capped_from_settings() -> None:
    provider = GeminiProvider(api_key="test-key")
    assert provider._client._api_client._http_options.timeout == 600_000


def test_explicit_http_options_timeout_is_respected() -> None:
    provider = GeminiProvider(api_key="test-key", http_options=genai_types.HttpOptions(timeout=5_000))
    assert provider._client._api_client._http_options.timeout == 5_000
