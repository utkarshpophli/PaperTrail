"""Google Gemini adapter.

The deliberately-different-shaped provider in this phase's scope (see
AI_PROVIDERS.md's scope note): Gemini's SDK is not OpenAI-compatible, which
is exactly the point — it proves ``AIProvider`` isn't secretly OpenAI-shaped.
Uses the current ``google-genai`` SDK's native schema-constrained JSON output
(``response_schema``/``response_mime_type``) rather than prompt-instructed
JSON, verified against the installed SDK version (see PR description).
"""

import json
from collections.abc import AsyncIterator

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger
from app.providers.base import LiveModel, ModelInfo, require_model
from app.providers.errors import AuthenticationError, NotSupportedError, ProviderUnavailableError
from app.providers.media import detect_image_mime_type
from app.providers.model_kinds import classify_model_id
from app.providers.redaction import redact_secrets
from app.providers.structured_output import generate_structured, stream_structured

logger = get_logger(__name__)


def _gemini_schema(schema: type[BaseModel]) -> dict:
    """Google's ``genai_types.Schema`` has no ``discriminator``/``oneOf``
    fields (only ``anyOf``) -- passing a Pydantic discriminated union
    (e.g. ``StorySpecOutput``'s 11-variant ``visual`` field) straight
    through as ``response_schema`` makes the SDK's own schema validation
    raise ``extra_forbidden``, which crashes the whole request. The ``type``
    literal already required on each union member still fully constrains
    which variant is valid -- ``discriminator`` is a validation-perf hint,
    not a correctness requirement -- so dropping it and renaming
    ``oneOf``->``anyOf`` keeps the same constraint in a shape Gemini accepts.

    Separately, ``additionalProperties: false`` (emitted by any model using
    ``model_config = ConfigDict(extra="forbid")``, e.g. every model in this
    schema) round-trips through the SDK's own ``Schema`` type fine locally,
    but the live API rejects the wire request with 400 "Unknown name
    additional_properties" -- confirmed against the real API, not just the
    SDK's local schema validation. Gemini's structured-output generation is
    already constrained to the declared ``properties``/``required`` fields,
    so dropping this key loses no real constraint."""

    def strip(node: object) -> object:
        if isinstance(node, dict):
            node.pop("discriminator", None)
            node.pop("additionalProperties", None)
            if "oneOf" in node:
                node["anyOf"] = node.pop("oneOf")
            return {key: strip(value) for key, value in node.items()}
        if isinstance(node, list):
            return [strip(item) for item in node]
        return node

    return strip(schema.model_json_schema())


# Google's exact (undocumented-format, so matched as a substring) message
# when a schema's combinatorial shape exceeds what constrained decoding can
# serve -- confirmed live against StorySpecOutput's 11-variant visual union
# nested inside a list of sections. Not a bug in the schema conversion above;
# Gemini's grammar-constrained generation has a real complexity ceiling.
_SCHEMA_TOO_COMPLEX_MARKER = "too many states for serving"


class _SchemaTooComplexForGemini(Exception):
    """Internal signal only -- never raised past this module. Triggers a
    single fallback to prompt-embedded JSON (same technique
    OpenAICompatibleProvider uses for providers without native JSON-schema
    constraining), relying on the shared generate_structured/stream_structured
    retry-on-invalid-output loop for correctness instead of API-level
    grammar constraints."""


def _is_schema_too_complex(exc: genai_errors.ClientError) -> bool:
    return exc.code == 400 and _SCHEMA_TOO_COMPLEX_MARKER in str(exc)


def _schema_prompt(prompt: str, schema: type[BaseModel]) -> str:
    return (
        f"{prompt}\n\n"
        "Respond with ONLY valid JSON matching this schema (no prose, no code fences):\n"
        f"{json.dumps(schema.model_json_schema())}"
    )


# ponytail: test-scaffolding only -- see anthropic.py's DEFAULT_MODEL comment.
DEFAULT_MODEL = "gemini-2.5-flash"
_EMBEDDING_MODEL = "gemini-embedding-001"

# ponytail: hand-curated against Google's published catalogue at
# implementation time (2026-09) — Gemini's catalogue is small/stable enough
# that a static list beats a live models.list() round trip from a
# synchronous interface method. Refresh when Google ships new GA models.
_KNOWN_MODELS: list[ModelInfo] = [
    ModelInfo(id="gemini-2.5-pro", label="Gemini 2.5 Pro", capabilities=["generate", "stream", "vision"]),
    ModelInfo(id="gemini-2.5-flash", label="Gemini 2.5 Flash", capabilities=["generate", "stream", "vision"]),
    ModelInfo(
        id="gemini-2.5-flash-lite", label="Gemini 2.5 Flash Lite", capabilities=["generate", "stream", "vision"]
    ),
    ModelInfo(id="gemini-2.0-flash", label="Gemini 2.0 Flash", capabilities=["generate", "stream", "vision"]),
    ModelInfo(id=_EMBEDDING_MODEL, label="Gemini Embedding", capabilities=["embed"]),
]


class GeminiProvider:
    """Implements ``AIProvider`` against Google's Gemini API.

    ``api_key`` is supplied per call site (per-request or per saved
    connection) — never read from settings/environment, never logged
    (SECURITY.md). ``http_options`` exists only so tests can inject a mock
    transport; production callers never pass it.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        http_options: genai_types.HttpOptions | None = None,
    ) -> None:
        self._model = model
        # Kept only for redacting upstream error text in logs (SECURITY.md:
        # never echo a provider's raw response body back to the caller).
        self._api_key = api_key
        # The SDK's request timeout is in milliseconds and applies to the whole
        # request; without a cap a hung call would never surface to the user.
        # An explicit caller-supplied timeout is respected.
        options = http_options or genai_types.HttpOptions()
        if options.timeout is None:
            options = options.model_copy(update={"timeout": int(get_settings().provider_read_timeout_seconds * 1000)})
        self._client = genai.Client(api_key=api_key, http_options=options)

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        model = require_model(opts)

        async def call(p: str) -> str:
            return await self._call_once(p, schema, model)

        return await generate_structured(schema, call, prompt)

    async def stream(self, prompt: str, schema: type[BaseModel], **opts: object) -> AsyncIterator[str]:
        model = require_model(opts)

        async def call(p: str) -> str:
            return await self._call_once(p, schema, model)

        def stream_call(p: str) -> AsyncIterator[str]:
            return self._call_stream(p, schema, model)

        async for chunk in stream_structured(schema, stream_call, call, prompt):
            yield chunk

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        try:
            response = await self._client.aio.models.embed_content(model=model, contents=texts)
        except genai_errors.ClientError as exc:
            raise self._map_client_error(exc, "embedding") from exc
        except genai_errors.ServerError as exc:
            self._log_upstream_error(exc, "embedding")
            raise ProviderUnavailableError("Gemini embedding request failed") from exc
        return [list(embedding.values or []) for embedding in (response.embeddings or [])]

    async def vision(self, image: bytes, prompt: str) -> str:
        try:
            mime_type = detect_image_mime_type(image)
        except ValueError as exc:
            raise NotSupportedError(f"Gemini vision: {exc}") from exc

        part = genai_types.Part.from_bytes(data=image, mime_type=mime_type)
        try:
            response = await self._client.aio.models.generate_content(model=self._model, contents=[part, prompt])
        except genai_errors.ClientError as exc:
            raise self._map_client_error(exc, "vision") from exc
        except genai_errors.ServerError as exc:
            self._log_upstream_error(exc, "vision")
            raise ProviderUnavailableError("Gemini vision request failed") from exc
        return response.text or ""

    def available_models(self) -> list[ModelInfo]:
        return list(_KNOWN_MODELS)

    async def list_models(self) -> list[LiveModel]:
        models: list[LiveModel] = []
        try:
            pager = await self._client.aio.models.list()
            async for model in pager:
                model_id = (model.name or "").removeprefix("models/")
                if not model_id:
                    continue
                actions = set(model.supported_actions or [])
                if "generateContent" in actions:
                    kind = classify_model_id(model_id)
                elif actions & {"embedContent", "batchEmbedContents"} or "embed" in model_id:
                    kind = "embedding"
                else:
                    kind = "other"
                models.append(
                    LiveModel(
                        id=model_id,
                        label=model.display_name or model_id,
                        context_length=model.input_token_limit,
                        kind=kind,
                    )
                )
        except genai_errors.ClientError as exc:
            raise self._map_client_error(exc, "models") from exc
        except genai_errors.ServerError as exc:
            self._log_upstream_error(exc, "models")
            raise ProviderUnavailableError("Gemini model listing failed") from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Gemini model listing timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Gemini model listing failed: {type(exc).__name__}") from exc
        return models

    async def _call_once(self, prompt: str, schema: type[BaseModel], model: str) -> str:
        try:
            response = await self._generate_content(prompt, schema, model, constrained=True)
        except _SchemaTooComplexForGemini:
            response = await self._generate_content(prompt, schema, model, constrained=False)
        return response.text or ""

    async def _generate_content(
        self, prompt: str, schema: type[BaseModel], model: str, *, constrained: bool
    ) -> genai_types.GenerateContentResponse:
        if constrained:
            config = genai_types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=_gemini_schema(schema)
            )
            contents = prompt
        else:
            config = genai_types.GenerateContentConfig(response_mime_type="application/json")
            contents = _schema_prompt(prompt, schema)
        try:
            return await self._client.aio.models.generate_content(model=model, contents=contents, config=config)
        except genai_errors.ClientError as exc:
            if constrained and _is_schema_too_complex(exc):
                raise _SchemaTooComplexForGemini from exc
            raise self._map_client_error(exc, "generate") from exc
        except genai_errors.ServerError as exc:
            self._log_upstream_error(exc, "generate")
            raise ProviderUnavailableError("Gemini request failed") from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Gemini request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Gemini request failed: {type(exc).__name__}") from exc

    async def _call_stream(self, prompt: str, schema: type[BaseModel], model: str) -> AsyncIterator[str]:
        try:
            stream = await self._start_stream(prompt, schema, model, constrained=True)
        except _SchemaTooComplexForGemini:
            stream = await self._start_stream(prompt, schema, model, constrained=False)
        try:
            async for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except genai_errors.ClientError as exc:
            raise self._map_client_error(exc, "stream") from exc
        except genai_errors.ServerError as exc:
            self._log_upstream_error(exc, "stream")
            raise ProviderUnavailableError("Gemini stream request failed") from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Gemini stream request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Gemini stream request failed: {type(exc).__name__}") from exc

    async def _start_stream(self, prompt: str, schema: type[BaseModel], model: str, *, constrained: bool) -> AsyncIterator:
        if constrained:
            config = genai_types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=_gemini_schema(schema)
            )
            contents = prompt
        else:
            config = genai_types.GenerateContentConfig(response_mime_type="application/json")
            contents = _schema_prompt(prompt, schema)
        try:
            return await self._client.aio.models.generate_content_stream(model=model, contents=contents, config=config)
        except genai_errors.ClientError as exc:
            if constrained and _is_schema_too_complex(exc):
                raise _SchemaTooComplexForGemini from exc
            raise self._map_client_error(exc, "stream") from exc
        except genai_errors.ServerError as exc:
            self._log_upstream_error(exc, "stream")
            raise ProviderUnavailableError("Gemini stream request failed") from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Gemini stream request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Gemini stream request failed: {type(exc).__name__}") from exc

    def _map_client_error(self, exc: genai_errors.ClientError, stage: str) -> Exception:
        # Upstream body is logged only, never echoed to the caller (SECURITY.md
        # / the "never echo upstream response body" rule the other adapters
        # already follow) -- Google's error text can carry request/account
        # detail that doesn't belong in a client-visible API response.
        self._log_upstream_error(exc, stage)
        if exc.code in (401, 403) or self._is_invalid_api_key(exc):
            return AuthenticationError(f"Gemini authentication failed during {stage}")
        if exc.code == 404:
            return ProviderUnavailableError(f"Gemini model not found during {stage}")
        if exc.code == 429:
            return ProviderUnavailableError(f"Gemini rate limit exceeded during {stage}")
        return ProviderUnavailableError(f"Gemini request failed during {stage} ({exc.code})")

    def _log_upstream_error(self, exc: genai_errors.ClientError | genai_errors.ServerError, stage: str) -> None:
        logger.warning(
            "gemini_request_failed stage=%s code=%s body=%s",
            stage,
            getattr(exc, "code", None),
            redact_secrets(str(exc.message)[:500], (self._api_key,)),
        )

    @staticmethod
    def _is_invalid_api_key(exc: genai_errors.ClientError) -> bool:
        # Google returns HTTP 400 (not 401/403) for an invalid API key, with
        # the real signal buried in a structured reason code — confirmed
        # against a live call with a bad key, not assumed. Checking the
        # reason code (not exc.message's wording, which is a display string
        # that could be reworded/localized) is what makes this reliable.
        try:
            details = exc.details.get("error", {}).get("details", [])
        except AttributeError:
            return False
        return any(isinstance(d, dict) and d.get("reason") == "API_KEY_INVALID" for d in details)
