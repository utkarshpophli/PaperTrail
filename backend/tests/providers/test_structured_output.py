"""Unit tests for the shared retry/validate loop — the "one shared place"
both Gemini and OpenAICompatibleProvider route through (AI_PROVIDERS.md's
hallucination handling: one retry with validation feedback, then raise)."""

import pytest

from app.providers.errors import StructuredOutputError
from app.providers.structured_output import generate_structured, stream_structured
from tests.providers.sample_schema import SampleClaim

VALID_JSON = '{"claim_text": "x improves y", "page": 3, "confidence": 0.9, "source_excerpt": "x improves y by 10%"}'
INVALID_JSON = '{"claim_text": "x improves y", "page": "not-a-number"}'


async def test_generate_structured_succeeds_first_try() -> None:
    calls: list[str] = []

    async def call(prompt: str) -> str:
        calls.append(prompt)
        return VALID_JSON

    result = await generate_structured(SampleClaim, call, "extract the claim")

    assert isinstance(result, SampleClaim)
    assert result.page == 3
    assert len(calls) == 1


async def test_generate_structured_retries_exactly_once_then_succeeds() -> None:
    calls: list[str] = []

    async def call(prompt: str) -> str:
        calls.append(prompt)
        return INVALID_JSON if len(calls) == 1 else VALID_JSON

    result = await generate_structured(SampleClaim, call, "extract the claim")

    assert isinstance(result, SampleClaim)
    assert len(calls) == 2
    # the retry prompt must carry the validation feedback, not just repeat
    assert "extract the claim" in calls[1]
    assert "validation error" in calls[1].lower() or "did not match" in calls[1].lower()


async def test_generate_structured_raises_after_second_failure() -> None:
    calls: list[str] = []

    async def call(prompt: str) -> str:
        calls.append(prompt)
        return INVALID_JSON

    with pytest.raises(StructuredOutputError):
        await generate_structured(SampleClaim, call, "extract the claim")

    assert len(calls) == 2  # never loops beyond the one retry


async def test_stream_structured_yields_chunks_and_validates_at_end() -> None:
    chunks_sent = ['{"claim_text": "x improves y", ', '"page": 3, "confidence": 0.9, ', '"source_excerpt": "x improves y"}']

    async def stream_call(prompt: str):
        for chunk in chunks_sent:
            yield chunk

    async def call(prompt: str) -> str:
        raise AssertionError("retry call should not happen when the stream already validated")

    received = [chunk async for chunk in stream_structured(SampleClaim, stream_call, call, "extract")]

    assert received == chunks_sent


async def test_stream_structured_retries_once_on_invalid_accumulated_output() -> None:
    async def stream_call(prompt: str):
        yield '{"claim_text": "bad", '
        yield '"page": "nope"}'

    retry_calls: list[str] = []

    async def call(prompt: str) -> str:
        retry_calls.append(prompt)
        return VALID_JSON

    received = [chunk async for chunk in stream_structured(SampleClaim, stream_call, call, "extract")]

    assert len(retry_calls) == 1
    assert received[-1] == VALID_JSON  # corrected output appended as the final chunk


async def test_stream_structured_raises_if_retry_also_invalid() -> None:
    async def stream_call(prompt: str):
        yield '{"page": "nope"}'

    async def call(prompt: str) -> str:
        return '{"page": "still-nope"}'

    with pytest.raises(StructuredOutputError):
        async for _ in stream_structured(SampleClaim, stream_call, call, "extract"):
            pass
