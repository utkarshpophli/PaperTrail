"""Shared structured-output validation + one-retry logic.

Both ``GeminiProvider`` and ``OpenAICompatibleProvider`` route their
``generate``/``stream`` through the two functions here instead of each
re-implementing the same "validate, retry once with feedback, then raise"
loop (AI_PROVIDERS.md's hallucination handling: "Structured-output
validation failure triggers one retry with the specific validation errors
fed back to the model; a second failure surfaces to the user").
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from app.providers.errors import StructuredOutputError

_ModelCall = Callable[[str], Awaitable[str]]
_StreamCall = Callable[[str], AsyncIterator[str]]


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.strip("`")
    if body.lower().startswith("json"):
        body = body[4:]
    return body.strip()


def _parse_and_validate(schema: type[BaseModel], raw: str) -> tuple[BaseModel | None, str | None]:
    """Returns ``(parsed, None)`` on success or ``(None, error_detail)`` on
    failure — never raises, so callers can decide whether to retry."""
    try:
        data = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as exc:
        return None, f"Response was not valid JSON: {exc}"
    try:
        return schema.model_validate(data), None
    except ValidationError as exc:
        return None, str(exc)


def _repair_prompt(original_prompt: str, error_detail: str) -> str:
    return (
        f"{original_prompt}\n\n"
        "Your previous response did not match the required schema. "
        f"Validation error:\n{error_detail}\n\n"
        "Return ONLY corrected JSON matching the schema — no prose, no code fences."
    )


async def generate_structured(schema: type[BaseModel], call: _ModelCall, prompt: str) -> BaseModel:
    """One provider round-trip via ``call``; on schema-validation failure,
    exactly one retry with the validation error fed back; a second failure
    raises ``StructuredOutputError``."""
    raw = await call(prompt)
    parsed, error_detail = _parse_and_validate(schema, raw)
    if parsed is not None:
        return parsed

    retry_raw = await call(_repair_prompt(prompt, error_detail or "unknown validation error"))
    retried, retry_error_detail = _parse_and_validate(schema, retry_raw)
    if retried is not None:
        return retried

    raise StructuredOutputError(
        f"Model output failed schema validation twice for {schema.__name__}: {retry_error_detail}"
    )


async def stream_structured(
    schema: type[BaseModel], stream_call: _StreamCall, call: _ModelCall, prompt: str
) -> AsyncIterator[str]:
    """Yields text deltas live as the first attempt streams in (so the UI can
    show progress immediately), then validates the accumulated text.

    On failure, the one retry is a fresh non-streaming call (the first
    attempt's chunks already reached the caller, so there is nothing left to
    "re-stream" for that attempt) — its corrected text is yielded as one
    final chunk. A second failure raises ``StructuredOutputError``, ending
    the generator with an exception rather than silently accepting invalid
    output.
    """
    chunks: list[str] = []
    async for chunk in stream_call(prompt):
        chunks.append(chunk)
        yield chunk

    parsed, error_detail = _parse_and_validate(schema, "".join(chunks))
    if parsed is not None:
        return

    retry_raw = await call(_repair_prompt(prompt, error_detail or "unknown validation error"))
    retried, retry_error_detail = _parse_and_validate(schema, retry_raw)
    if retried is None:
        raise StructuredOutputError(
            f"Model output failed schema validation twice for {schema.__name__}: {retry_error_detail}"
        )
    yield retry_raw
