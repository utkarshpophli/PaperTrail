"""Scrubs a request's own credentials out of provider failures.

A provider error can echo the credential it was given (a URL with ``?key=``,
an SDK message quoting the header, a proxy error page). Services log those
errors and stream them to the client as ``AnalysisEvent`` messages, so without
this an API key that never touches a log line directly can still leak through
exception text. The service that built the provider is the one place that
holds both the secret and the exception, so it wraps the provider here.
"""

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from app.providers.base import AIProvider, LiveModel

_REDACTED = "[redacted]"
# Shorter values would mangle ordinary words in error text; real credentials
# are far longer.
_MIN_SECRET_LENGTH = 6


def redact_secrets(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if len(secret) >= _MIN_SECRET_LENGTH:
            text = text.replace(secret, _REDACTED)
    return text


def _scrub_exception(exc: BaseException, secrets: tuple[str, ...]) -> None:
    exc.args = tuple(redact_secrets(arg, secrets) if isinstance(arg, str) else arg for arg in exc.args)
    message = getattr(exc, "message", None)
    if isinstance(message, str):
        exc.message = redact_secrets(message, secrets)  # type: ignore[attr-defined]


class RedactingProvider:
    """Delegates to ``inner`` and scrubs ``secrets`` from any exception it
    raises. Exceptions keep their type (services catch on it); only their
    text changes."""

    def __init__(self, inner: AIProvider, secrets: tuple[str, ...]) -> None:
        self._inner = inner
        self._secrets = secrets

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        try:
            return await self._inner.generate(prompt, schema, **opts)
        except Exception as exc:
            _scrub_exception(exc, self._secrets)
            raise

    async def stream(self, prompt: str, schema: type[BaseModel], **opts: object) -> AsyncIterator[str]:
        try:
            async for delta in self._inner.stream(prompt, schema, **opts):
                yield delta
        except Exception as exc:
            _scrub_exception(exc, self._secrets)
            raise

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        try:
            return await self._inner.embed(texts, model=model)
        except Exception as exc:
            _scrub_exception(exc, self._secrets)
            raise

    async def vision(self, image: bytes, prompt: str) -> str:
        try:
            return await self._inner.vision(image, prompt)
        except Exception as exc:
            _scrub_exception(exc, self._secrets)
            raise

    def available_models(self) -> Any:
        return self._inner.available_models()

    async def list_models(self) -> list[LiveModel]:
        try:
            return await self._inner.list_models()
        except Exception as exc:
            _scrub_exception(exc, self._secrets)
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def redacting(provider: AIProvider, *secrets: str | None) -> AIProvider:
    """``provider`` unchanged when there is nothing to redact."""
    present = tuple(secret for secret in secrets if secret)
    return RedactingProvider(provider, present) if present else provider  # type: ignore[return-value]
