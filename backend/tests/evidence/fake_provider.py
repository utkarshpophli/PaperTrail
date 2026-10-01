"""A minimal ``AIProvider``-shaped test double -- stands in for a real
provider adapter (Gemini/NVIDIA NIM/Ollama), per TESTING.md: "Mock external
AI provider APIs (cost, nondeterminism, latency), not internal boundaries."
"""

from collections.abc import AsyncIterator

from pydantic import BaseModel

from app.providers.base import ModelInfo
from app.providers.errors import NotSupportedError
from app.providers.ping import _PingResponse


class FakeProvider:
    """Returns a pre-baked response per output schema, and records every
    prompt it was called with (for asserting on prompt structure/content).
    """

    def __init__(self, responses: dict[type[BaseModel], BaseModel]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, type[BaseModel]]] = []

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        self.calls.append((prompt, schema))
        # run_analysis's preflight liveness ping always asks for this schema
        # first -- answer it without requiring every test's response dict to
        # know about it.
        if schema is _PingResponse:
            return _PingResponse(ok=True)
        return self._responses[schema]

    def stream(self, prompt: str, schema: type[BaseModel], **opts: object) -> AsyncIterator[str]:
        raise NotImplementedError("FakeProvider does not support stream()")

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotSupportedError("FakeProvider does not support embed()")

    async def vision(self, image: bytes, prompt: str) -> str:
        raise NotSupportedError("FakeProvider does not support vision()")

    def available_models(self) -> list[ModelInfo]:
        return []


class FailingProvider:
    """Raises a fixed exception from every ``generate`` call, to test error
    propagation out of ``run_extraction``/``run_analysis``."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        raise self._exc

    def stream(self, prompt: str, schema: type[BaseModel], **opts: object) -> AsyncIterator[str]:
        raise NotImplementedError

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotSupportedError("unused")

    async def vision(self, image: bytes, prompt: str) -> str:
        raise NotSupportedError("unused")

    def available_models(self) -> list[ModelInfo]:
        return []
