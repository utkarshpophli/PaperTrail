"""llama.cpp ``llama-server`` adapter — local OpenAI-compatible endpoint
(default http://localhost:8080), no auth, loopback-only."""

import httpx

from app.providers.base import ModelInfo
from app.providers.local_endpoint import openai_base_url, validate_loopback_endpoint
from app.providers.openai_compatible import OpenAICompatibleProvider

# llama-server serves the one model it was started with and ignores this id.
# ponytail: test-scaffolding only -- see anthropic.py's DEFAULT_MODEL comment.
DEFAULT_MODEL = "local-model"


class LlamaCppProvider(OpenAICompatibleProvider):
    # Embeddings need the server started with --embedding and vision needs an
    # mmproj file; neither is discoverable, so fail loud instead of guessing.
    supports_embed = False
    supports_vision = False
    supports_json_mode = False

    def __init__(
        self,
        *,
        endpoint: str,
        model: str = DEFAULT_MODEL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        validate_loopback_endpoint(endpoint)
        super().__init__(base_url=openai_base_url(endpoint), model=model, api_key=None, transport=transport)

    def available_models(self) -> list[ModelInfo]:
        return []
