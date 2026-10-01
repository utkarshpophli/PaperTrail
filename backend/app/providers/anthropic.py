"""Anthropic adapter — Messages API over httpx (``POST /v1/messages``).

Not OpenAI-shaped: the credential goes in ``x-api-key``, ``max_tokens`` is
mandatory, the system prompt is a top-level field, and text lives in
``content[].text`` blocks. Anthropic has no schema-constrained JSON mode, so
structured output is prompt-instructed and validated by
``app.providers.structured_output`` (one retry with the validation error).
Host is fixed: an api_key provider never accepts a user-supplied base URL.

Every request streams on the wire (even ``generate``) and is reassembled
here, so a large ``max_tokens`` never risks an HTTP timeout. Retries and the
operation deadline are the same policy as the OpenAI-compatible family
(``app.providers.retry``).
"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator

import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger
from app.providers.base import LiveModel, ModelInfo, require_model
from app.providers.errors import (
    AuthenticationError,
    InvalidConfigError,
    ModelNotFoundError,
    NotSupportedError,
    OutputTruncatedError,
    ProviderUnavailableError,
)
from app.providers.media import detect_image_mime_type
from app.providers.model_kinds import classify_model_id
from app.providers.redaction import redact_secrets
from app.providers.retry import (
    retry_delay,
    retry_transient_exception,
    send_with_retry,
    should_retry_status,
    within_deadline,
)
from app.providers.structured_output import generate_structured, stream_structured
from app.providers.timeouts import LIST_MODELS_TIMEOUT, default_timeout

logger = get_logger(__name__)

_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
_ANTHROPIC_VERSION = "2023-06-01"
# ponytail: test-scaffolding only -- registry.build_provider() no longer
# passes this at construction, and require_model() blocks any call that
# omits an explicit model, so this constructor default can never reach a
# real request in production.
DEFAULT_MODEL = "claude-opus-5-5"
# Streamed, so no HTTP-timeout reason to keep this low. 64K fits every listed
# model's output cap (Haiku 4.5's is the smallest) and leaves room for a
# 300-metric extraction plus adaptive thinking, which counts against it.
_DEFAULT_MAX_TOKENS = 64000
_LIST_PAGE_SIZE = 100
_LIST_MAX_PAGES = 5  # 500 models is far beyond Anthropic's catalogue; bounds a misbehaving cursor

_SYSTEM_PROMPT = "Respond with ONLY valid JSON matching this schema (no prose, no code fences):\n{schema}"

# Fallback suggestions only — the live /v1/models listing is the source of
# truth and any freeform model id is accepted.
_KNOWN_MODELS: list[ModelInfo] = [
    ModelInfo(id="claude-opus-5-5", label="Claude Opus 5.5", capabilities=["generate", "stream", "vision"]),
    ModelInfo(id="claude-sonnet-5-5", label="Claude Sonnet 5.5", capabilities=["generate", "stream", "vision"]),
    ModelInfo(id="claude-haiku-4-5", label="Claude Haiku 4.5", capabilities=["generate", "stream", "vision"]),
]


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout: float | None = None,
        operation_timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise InvalidConfigError("Anthropic requires an api_key")
        self._api_key = api_key
        self._model = model
        self._timeout = httpx.Timeout(timeout) if timeout is not None else default_timeout()
        self._operation_timeout_seconds = (
            operation_timeout if operation_timeout is not None else get_settings().provider_operation_timeout_seconds
        )
        self._transport = transport  # test-only: injects a MockTransport

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        async def call(p: str) -> str:
            return await self._call_once(p, schema, opts)

        return await within_deadline(
            "AnthropicProvider", "generation", self._operation_timeout_seconds, generate_structured(schema, call, prompt)
        )

    async def stream(self, prompt: str, schema: type[BaseModel], **opts: object) -> AsyncIterator[str]:
        async def call(p: str) -> str:
            return await self._call_once(p, schema, opts)

        def stream_call(p: str) -> AsyncIterator[str]:
            return self._call_stream(p, schema, opts)

        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                async for chunk in stream_structured(schema, stream_call, call, prompt):
                    yield chunk
        except TimeoutError as exc:
            raise ProviderUnavailableError(
                f"Streaming did not complete within {self._operation_timeout_seconds:.0f}s"
            ) from exc

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotSupportedError("Anthropic does not offer an embeddings API")

    async def vision(self, image: bytes, prompt: str) -> str:
        try:
            mime_type = detect_image_mime_type(image)
        except ValueError as exc:
            raise NotSupportedError(f"Anthropic vision: {exc}") from exc
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": base64.b64encode(image).decode("ascii")}},
            {"type": "text", "text": prompt},
        ]
        payload = {"model": self._model, "max_tokens": _DEFAULT_MAX_TOKENS, "messages": [{"role": "user", "content": content}]}
        return await within_deadline("AnthropicProvider", "vision", self._operation_timeout_seconds, self._complete(payload))

    def available_models(self) -> list[ModelInfo]:
        return list(_KNOWN_MODELS)

    async def list_models(self) -> list[LiveModel]:
        """``GET /v1/models`` is cursor-paginated (``has_more``/``last_id``)."""
        models: list[LiveModel] = []
        after_id: str | None = None
        for _ in range(_LIST_MAX_PAGES):
            params: dict[str, str | int] = {"limit": _LIST_PAGE_SIZE}
            if after_id:
                params["after_id"] = after_id
            page = await self._get("/models", params)
            try:
                for entry in page["data"]:
                    name = entry.get("display_name")
                    models.append(
                        LiveModel(
                            id=entry["id"],
                            label=name if isinstance(name, str) and name else entry["id"],
                            kind=classify_model_id(entry["id"]),
                        )
                    )
                more = bool(page.get("has_more")) and isinstance(page.get("last_id"), str)
            except (KeyError, TypeError, AttributeError) as exc:
                raise ProviderUnavailableError("Unexpected Anthropic models response shape") from exc
            if not more:
                break
            after_id = page["last_id"]
        return models

    def _messages_payload(self, prompt: str, schema: type[BaseModel], opts: dict[str, object]) -> dict[str, object]:
        max_tokens = opts.get("max_tokens", _DEFAULT_MAX_TOKENS)
        return {
            "model": require_model(opts),
            "max_tokens": max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else _DEFAULT_MAX_TOKENS,
            "system": _SYSTEM_PROMPT.format(schema=json.dumps(schema.model_json_schema())),
            "messages": [{"role": "user", "content": prompt}],
        }

    async def _call_once(self, prompt: str, schema: type[BaseModel], opts: dict[str, object]) -> str:
        return await self._complete(self._messages_payload(prompt, schema, opts))

    async def _complete(self, payload: dict[str, object]) -> str:
        text: list[str] = []
        stop_reason: str | None = None
        async for kind, value in self._iter_stream(payload):
            if kind == "text":
                text.append(value)
            else:
                stop_reason = value
        _check_stop_reason(stop_reason)
        return "".join(text)

    async def _call_stream(self, prompt: str, schema: type[BaseModel], opts: dict[str, object]) -> AsyncIterator[str]:
        stop_reason: str | None = None
        async for kind, value in self._iter_stream(self._messages_payload(prompt, schema, opts)):
            if kind == "text":
                yield value
            else:
                stop_reason = value
        _check_stop_reason(stop_reason)

    async def _iter_stream(self, payload: dict[str, object]) -> AsyncIterator[tuple[str, str]]:
        """Yields ``("text", delta)`` and ``("stop", stop_reason)`` from one
        streamed Messages request. Retries only before the first event -- a
        restart after that would replay output the caller already consumed."""
        payload = {**payload, "stream": True}
        model = str(payload["model"])
        url = f"{_ANTHROPIC_BASE_URL}/messages"
        attempt = 0
        received = False
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            while True:
                try:
                    async with client.stream("POST", url, json=payload, headers=self._headers()) as response:
                        if should_retry_status(response.status_code, attempt):
                            await response.aread()
                            await asyncio.sleep(retry_delay(response, attempt))
                            attempt += 1
                            continue
                        await self._raise_for_status(response, "messages", model)
                        if "text/event-stream" not in response.headers.get("content-type", ""):
                            # A non-streamed message body (a proxy that ignored "stream").
                            await response.aread()
                            received = True
                            data = response.json()
                            yield "text", self._extract_text(data)
                            yield "stop", str(data.get("stop_reason") or "")
                            return
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            try:
                                event = json.loads(line[len("data:") :].strip())
                            except json.JSONDecodeError:
                                continue
                            received = True
                            if event.get("type") == "error":
                                raise ProviderUnavailableError("Anthropic stream reported an error event")
                            delta = event.get("delta") or {}
                            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                                yield "text", delta.get("text", "")
                            elif event.get("type") == "message_delta" and delta.get("stop_reason"):
                                yield "stop", delta["stop_reason"]
                        return
                except (httpx.TimeoutException, httpx.HTTPError) as exc:
                    if received:
                        raise ProviderUnavailableError(
                            f"Anthropic streaming response was interrupted: {type(exc).__name__}"
                        ) from exc
                    attempt = await retry_transient_exception(exc, attempt, url, "Anthropic request")

    async def _get(self, path: str, params: dict[str, str | int]) -> dict:
        url = f"{_ANTHROPIC_BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=LIST_MODELS_TIMEOUT, transport=self._transport) as client:
            response = await send_with_retry(lambda: client.get(url, params=params, headers=self._headers()), url)
        await self._raise_for_status(response, path, self._model)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("Anthropic models response was not valid JSON") from exc

    async def _raise_for_status(self, response: httpx.Response, stage: str, model: str) -> None:
        # Upstream bodies are logged, never returned to the caller.
        status = response.status_code
        if status in (401, 403):
            raise AuthenticationError(f"Anthropic authentication failed during {stage} ({status})")
        if status == 404:
            raise ModelNotFoundError(f"Anthropic model '{model}' was not found (or is not available to this key)")
        if status == 429:
            raise ProviderUnavailableError(f"Anthropic rate limit exceeded during {stage}")
        if status >= 400:
            await response.aread()
            logger.warning("provider_request_failed stage=%s status=%s body=%s", stage, status, redact_secrets(response.text[:500], (self._api_key,)))
            raise ProviderUnavailableError(f"Anthropic request failed during {stage} ({status})")

    def _headers(self) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
        }

    def _extract_text(self, data: dict) -> str:
        try:
            return "".join(block["text"] for block in data["content"] if block.get("type") == "text")
        except (KeyError, TypeError, AttributeError) as exc:
            logger.warning("provider_unexpected_response stage=messages body=%s", redact_secrets(repr(data)[:500], (self._api_key,)))
            raise ProviderUnavailableError("Unexpected Anthropic messages response shape") from exc


def _check_stop_reason(stop_reason: str | None) -> None:
    """A cut-off or declined answer is not a schema problem: the structured-
    output repair retry can't fix it, so it fails here with the real reason
    instead of as a misleading "not valid JSON"."""
    if stop_reason == "max_tokens":
        raise OutputTruncatedError("Model hit its output-token limit (stop_reason=max_tokens) before finishing its answer")
    if stop_reason == "refusal":
        raise ProviderUnavailableError("Anthropic declined the request (stop_reason=refusal)")
