"""A minimal ``AIProvider``-shaped test double that also supports ``embed``
(``tests.evidence.fake_provider.FakeProvider`` deliberately does not) --
Discovery's ranking/extraction/clustering all call ``embed`` and/or
``generate`` in the same request, so this test double needs both.
"""

from collections.abc import AsyncIterator
from typing import Callable

from pydantic import BaseModel

from app.providers.base import ModelInfo
from app.providers.errors import NotSupportedError

ResponseFn = Callable[[str, type[BaseModel]], BaseModel]


class FakeDiscoveryProvider:
    def __init__(
        self,
        response_fn: ResponseFn,
        embeddings: dict[str, list[float]] | None = None,
        embed_error: Exception | None = None,
    ) -> None:
        self._response_fn = response_fn
        self._embeddings = embeddings or {}
        self._embed_error = embed_error
        self.generate_calls: list[tuple[str, type[BaseModel]]] = []
        self.embed_calls: list[list[str]] = []

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        self.generate_calls.append((prompt, schema))
        return self._response_fn(prompt, schema)

    def stream(self, prompt: str, schema: type[BaseModel], **opts: object) -> AsyncIterator[str]:
        raise NotImplementedError("FakeDiscoveryProvider does not support stream()")

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        if self._embed_error is not None:
            raise self._embed_error
        return [self._embeddings.get(text, [0.0, 0.0]) for text in texts]

    async def vision(self, image: bytes, prompt: str) -> str:
        raise NotSupportedError("FakeDiscoveryProvider does not support vision()")

    def available_models(self) -> list[ModelInfo]:
        return []
