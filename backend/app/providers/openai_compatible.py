"""Base class for any provider that speaks the OpenAI-compatible
``/chat/completions`` (+ ``/embeddings`` where supported) HTTP shape.

NVIDIA NIM, OpenAI, OpenRouter (cloud, API key) and Ollama, LM Studio,
llama.cpp (local, no auth) subclass this rather than each re-implementing
request/response handling and the structured-output retry loop. Uses
``httpx`` directly (already a pinned dependency) instead of adding an OpenAI
SDK dependency for a handful of JSON-over-HTTP calls.
"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Awaitable
from typing import NamedTuple, TypeVar

import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger
from app.providers.base import LiveModel, require_model
from app.providers.errors import (
    AuthenticationError,
    NotSupportedError,
    OutputTruncatedError,
    ProviderUnavailableError,
)
from app.providers.media import detect_image_mime_type
from app.providers.model_kinds import classify_model_id
from app.providers.rate_limit import acquire_rate_limit
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

_T = TypeVar("_T")


class _ChatChunk(NamedTuple):
    content: str
    reasoning: str
    finish_reason: str | None


def _resolve_answer(content: str, reasoning: str, finish_reason: str | None) -> str:
    """Picks the model's answer from a completed chat response.

    Some NIM-hosted reasoning models (confirmed live: deepseek-ai/
    deepseek-v4.1-flash, z-ai/glm-5.3-flash) leave the standard ``content``
    empty and put a short final answer in the non-standard
    ``reasoning_content`` field, on a normal ``finish_reason: "stop"``. That
    field is only used as the answer when the model actually finished --
    on ``"length"`` it holds an unfinished chain-of-thought (confirmed live:
    ~3k reasoning chunks, zero content, on a 37k-token extraction prompt),
    and feeding that to the JSON parser just produced a misleading "invalid
    JSON" error.
    """
    if finish_reason == "length":
        detail = " while still reasoning" if not content and reasoning else ""
        raise OutputTruncatedError(
            f"Model hit its output-token limit (finish_reason=length){detail} before finishing its answer"
        )
    return content or reasoning

class OpenAICompatibleProvider:
    """Not itself a full ``AIProvider`` for every provider — subclasses set
    ``supports_embed``/``supports_vision`` to reflect what's actually
    confirmed to work for that provider/model, per AI_PROVIDERS.md's "a
    provider that can't do X raises NotSupportedError, never a silent
    no-op."""

    supports_embed: bool = True
    supports_vision: bool = True
    # ``response_format={"type": "json_object"}`` is honoured by hosted APIs
    # but rejected or ignored by several local runtimes; those subclasses turn
    # it off and rely on schema validation + the one-retry path instead.
    supports_json_mode: bool = True
    # Extra fields merged into every /embeddings request body, beyond
    # {"model", "input"} -- e.g. NIM's retrieval embedders require an
    # "input_type". Empty for providers whose embeddings API needs nothing
    # extra.
    _embed_extra_body: dict[str, object] = {}

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float | None = None,
        operation_timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
        requests_per_minute: int | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout) if timeout is not None else default_timeout()
        self._operation_timeout_seconds = (
            operation_timeout if operation_timeout is not None else get_settings().provider_operation_timeout_seconds
        )
        self._transport = transport  # test-only: injects a MockTransport
        self._requests_per_minute = requests_per_minute

    async def _throttle(self) -> None:
        if self._requests_per_minute is not None:
            await acquire_rate_limit(self._base_url, self._api_key or "", self._requests_per_minute)

    async def _within_operation_deadline(self, operation: str, work: Awaitable[_T]) -> _T:
        return await within_deadline(type(self).__name__, operation, self._operation_timeout_seconds, work)

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        model = require_model(opts)

        async def call(p: str) -> str:
            return await self._call_once(p, schema, model)

        return await self._within_operation_deadline("generation", generate_structured(schema, call, prompt))

    async def stream(self, prompt: str, schema: type[BaseModel], **opts: object) -> AsyncIterator[str]:
        model = require_model(opts)

        async def call(p: str) -> str:
            return await self._call_once(p, schema, model)

        def stream_call(p: str) -> AsyncIterator[str]:
            return self._call_stream(p, schema, model)

        # Spans the whole streamed operation (opening the connection, every
        # SSE read, transport retries, and schema repair) -- see
        # _within_operation_deadline's docstring. Can't reuse that helper
        # directly since this is a generator, not a single awaitable.
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                async for chunk in stream_structured(schema, stream_call, call, prompt):
                    yield chunk
        except TimeoutError as exc:
            logger.warning(
                "provider_operation_timed_out provider=%s operation=streaming deadline_seconds=%s",
                type(self).__name__,
                self._operation_timeout_seconds,
            )
            raise ProviderUnavailableError(
                f"Streaming did not complete within {self._operation_timeout_seconds:.0f}s"
            ) from exc

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        if not self.supports_embed:
            raise NotSupportedError(f"{type(self).__name__} does not support embeddings")

        async def work() -> list[list[float]]:
            data = await self._post("/embeddings", {"model": model, "input": texts, **self._embed_extra_body})
            try:
                return [item["embedding"] for item in data["data"]]
            except (KeyError, TypeError) as exc:
                logger.warning(
                    "provider_unexpected_response stage=embeddings body=%s",
                    redact_secrets(repr(data)[:500], (self._api_key or "",)),
                )
                raise ProviderUnavailableError("Unexpected embeddings response shape") from exc

        return await self._within_operation_deadline("embedding", work())

    async def vision(self, image: bytes, prompt: str) -> str:
        if not self.supports_vision:
            raise NotSupportedError(f"{type(self).__name__} does not support vision")
        try:
            mime_type = detect_image_mime_type(image)
        except ValueError as exc:
            raise NotSupportedError(f"{type(self).__name__} vision: {exc}") from exc

        encoded = base64.b64encode(image).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                ],
            }
        ]
        return await self._complete({"model": self._model, "messages": messages, "stream": True})

    async def list_models(self) -> list[LiveModel]:
        """OpenAI shape: ``{"data": [{"id", ...}]}``. OpenRouter adds
        ``name``/``context_length``; both are used when present."""
        data = await self._get(f"{self._base_url}/models")
        try:
            entries = [entry for entry in data["data"] if isinstance(entry.get("id"), str)]
        except (KeyError, TypeError, AttributeError) as exc:
            raise ProviderUnavailableError("Unexpected models response shape") from exc
        return [self._to_live_model(entry) for entry in entries]

    @staticmethod
    def _to_live_model(entry: dict) -> LiveModel:
        context_length = entry.get("context_length")
        name = entry.get("name")
        return LiveModel(
            id=entry["id"],
            label=name if isinstance(name, str) and name else entry["id"],
            context_length=context_length if isinstance(context_length, int) else None,
            kind=classify_model_id(entry["id"]),
        )

    def _chat_payload(self, prompt: str, schema: type[BaseModel], model: str) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": model,
            "messages": [{"role": "user", "content": self._schema_prompt(prompt, schema)}],
        }
        if self.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def _call_once(self, prompt: str, schema: type[BaseModel], model: str) -> str:
        # Streamed on the wire even though the caller wants one string:
        # confirmed live that NVIDIA's gateway 504s a *non-streamed* request
        # at ~300s while it waits on the whole completion, but lets a
        # streamed one run for 16+ minutes. Accumulating the stream here
        # keeps generate()'s contract unchanged.
        return await self._complete({**self._chat_payload(prompt, schema, model), "stream": True})

    async def _complete(self, payload: dict[str, object]) -> str:
        content: list[str] = []
        reasoning: list[str] = []
        finish_reason: str | None = None
        async for chunk in self._iter_chat_chunks(payload):
            content.append(chunk.content)
            reasoning.append(chunk.reasoning)
            finish_reason = chunk.finish_reason or finish_reason
        return _resolve_answer("".join(content), "".join(reasoning), finish_reason)

    async def _call_stream(self, prompt: str, schema: type[BaseModel], model: str) -> AsyncIterator[str]:
        payload = {**self._chat_payload(prompt, schema, model), "stream": True}
        content: list[str] = []
        reasoning: list[str] = []
        finish_reason: str | None = None
        async for chunk in self._iter_chat_chunks(payload):
            if chunk.content:
                content.append(chunk.content)
                yield chunk.content
            reasoning.append(chunk.reasoning)
            finish_reason = chunk.finish_reason or finish_reason
        # Reasoning is buffered, never streamed out: a reasoning model sends
        # its whole chain-of-thought before the answer, and splicing that
        # into the output would corrupt the JSON being assembled.
        answer = _resolve_answer("".join(content), "".join(reasoning), finish_reason)
        if not content and answer:
            yield answer

    async def _iter_chat_chunks(self, payload: dict[str, object]) -> AsyncIterator[_ChatChunk]:
        """POSTs a streaming chat completion and yields each chunk's content,
        reasoning and finish_reason. Retries (see ``send_with_retry``) only
        before the first chunk arrives -- a restart after that would replay
        output the caller already consumed. Also accepts a plain JSON
        completion, for an OpenAI-compatible server that ignores
        ``"stream": true``."""
        url = f"{self._base_url}/chat/completions"
        await self._throttle()
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
                        await self._raise_for_status(response, "/chat/completions")
                        if "text/event-stream" not in response.headers.get("content-type", ""):
                            await response.aread()
                            received = True
                            yield self._chunk_from_completion(response)
                            return
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data_str = line[len("data:") :].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                event = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            choice = (event.get("choices") or [{}])[0]
                            delta = choice.get("delta") or {}
                            received = True
                            yield _ChatChunk(
                                delta.get("content") or "",
                                delta.get("reasoning_content") or "",
                                choice.get("finish_reason"),
                            )
                        return
                except (httpx.TimeoutException, httpx.HTTPError) as exc:
                    if received:
                        raise ProviderUnavailableError(
                            f"Streaming response from {url} was interrupted: {type(exc).__name__}"
                        ) from exc
                    attempt = await retry_transient_exception(exc, attempt, url, "Streaming request")
                    continue

    def _chunk_from_completion(self, response: httpx.Response) -> _ChatChunk:
        try:
            choice = response.json()["choices"][0]
            message = choice["message"]
            return _ChatChunk(message["content"] or "", message.get("reasoning_content") or "", choice.get("finish_reason"))
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning(
                "provider_unexpected_response stage=chat body=%s",
                redact_secrets(response.text[:500], (self._api_key or "",)),
            )
            raise ProviderUnavailableError("Unexpected chat completion response shape") from exc

    async def _post(self, path: str, payload: dict[str, object]) -> dict:
        url = f"{self._base_url}{path}"
        await self._throttle()
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await send_with_retry(lambda: client.post(url, json=payload, headers=self._headers()), url)
        await self._raise_for_status(response, path)
        return response.json()

    async def _get(self, url: str) -> dict:
        await self._throttle()
        async with httpx.AsyncClient(timeout=LIST_MODELS_TIMEOUT, transport=self._transport) as client:
            response = await send_with_retry(lambda: client.get(url, headers=self._headers()), url)
        await self._raise_for_status(response, "models")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("Models response was not valid JSON") from exc

    async def _raise_for_status(self, response: httpx.Response, stage: str) -> None:
        # The probed target's response body is never echoed back to the
        # caller — for a local/loopback provider (Ollama) that target is a
        # user-supplied endpoint, so its response content is exactly the
        # kind of thing an SSRF-to-service-enumeration attempt would want
        # leaked back (security review finding). Full detail goes to the
        # server log only; the raised error carries just the status code.
        if response.status_code in (401, 403):
            raise AuthenticationError(f"Authentication failed during {stage} ({response.status_code})")
        if response.status_code == 404:
            raise ProviderUnavailableError(f"Model or endpoint not found during {stage}")
        if response.status_code == 429:
            raise ProviderUnavailableError(f"Rate limit exceeded during {stage}")
        if response.status_code >= 400:
            # A ``client.stream()`` response body isn't read until consumed;
            # a plain ``client.post()`` response already is. ``aread()`` is
            # idempotent either way, so always call it before ``.text``.
            await response.aread()
            logger.warning("provider_request_failed stage=%s status=%s body=%s", stage, response.status_code, redact_secrets(response.text[:500], (self._api_key or "",)))
            raise ProviderUnavailableError(f"Request failed during {stage} ({response.status_code})")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @staticmethod
    def _schema_prompt(prompt: str, schema: type[BaseModel]) -> str:
        return (
            f"{prompt}\n\n"
            "Respond with ONLY valid JSON matching this schema (no prose, no code fences):\n"
            f"{json.dumps(schema.model_json_schema())}"
        )

