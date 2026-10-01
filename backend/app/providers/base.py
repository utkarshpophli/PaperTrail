"""The ``AIProvider`` interface — the one seam every provider adapter
implements (docs/AI_PROVIDERS.md). No module outside ``app/providers/``
imports a provider SDK directly; everything goes through this Protocol.

A provider never receives a raw document — document parsing already
happened upstream (see ARCHITECTURE.md's Document Pipeline). Providers only
ever see text/structured context, plus the optional ``vision`` path for a
single figure/table crop.
"""

from collections.abc import AsyncIterator
from typing import Literal, Protocol

from pydantic import BaseModel

from app.providers.errors import InvalidConfigError


def require_model(opts: dict[str, object]) -> str:
    """The one choke point every ``generate``/``stream`` call passes
    through. A caller that omits ``model`` gets a loud, typed error instead
    of the adapter silently substituting its own ``DEFAULT_MODEL`` -- that
    silent substitution is exactly what broke live in production once
    already (a stale NIM default started 410-ing)."""
    model = opts.get("model")
    if not isinstance(model, str) or not model.strip():
        raise InvalidConfigError("A model id is required")
    return model


class ModelInfo(BaseModel):
    """One entry in a provider's ``available_models()`` list."""

    id: str
    label: str
    capabilities: list[str]  # subset of "generate" | "stream" | "embed" | "vision"


ModelKind = Literal["chat", "embedding", "other"]


class LiveModel(BaseModel):
    """One model as reported by a provider's live listing endpoint — just
    what the model picker needs."""

    id: str
    label: str
    context_length: int | None = None
    kind: ModelKind = "chat"


class AIProvider(Protocol):
    """Every pipeline stage that calls an AI provider depends only on this
    interface — never on a specific provider's SDK or request shape.
    """

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        """Returns model output validated against ``schema``. Retries once
        with validation feedback on a schema mismatch; a second failure
        raises ``StructuredOutputError`` (AI_PROVIDERS.md's hallucination
        handling) rather than looping or accepting invalid output."""
        ...

    def stream(self, prompt: str, schema: type[BaseModel], **opts: object) -> AsyncIterator[str]:
        """Yields text deltas for progressive display. The accumulated text
        is still validated against ``schema`` with the same one-retry
        discipline as ``generate`` before the stream is considered done."""
        ...

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        """Raises ``NotSupportedError`` if this provider/model genuinely
        cannot embed — never a silent empty-list no-op. ``model`` is a
        required keyword (not an adapter-picked default) for the same
        reason ``generate``/``stream`` require one via ``require_model`` —
        a caller-omitted model must never silently fall back to a
        hardcoded id."""
        ...

    async def vision(self, image: bytes, prompt: str) -> str:
        """Raises ``NotSupportedError`` if this provider/model genuinely
        cannot do vision — never a silent no-op or text-only guess."""
        ...

    def available_models(self) -> list[ModelInfo]:
        """Synchronous by contract — implementations return a curated/cached
        list rather than making a blocking network call from a sync method,
        except where the target is loopback-local and effectively free
        (see ``OllamaProvider``)."""
        ...

    async def list_models(self) -> list[LiveModel]:
        """Live listing from the provider's own catalogue (all kinds, each
        classified). Raises a typed error on failure — the caller decides
        whether to fall back to ``available_models()``; this never silently
        returns a static list."""
        ...
