"""LM Studio adapter — local OpenAI-compatible server (default
http://localhost:1234), no auth, loopback-only like every local runtime."""

import httpx

from app.providers.base import ModelInfo
from app.providers.local_endpoint import openai_base_url, validate_loopback_endpoint
from app.providers.openai_compatible import OpenAICompatibleProvider

# LM Studio serves whatever model the user loaded; the id is required by the
# API shape but the user picks a real one from the live listing.
# ponytail: test-scaffolding only -- see anthropic.py's DEFAULT_MODEL comment.
DEFAULT_MODEL = "local-model"


class LMStudioProvider(OpenAICompatibleProvider):
    supports_embed = True  # only if an embedding model is loaded; upstream errors surface loudly
    supports_vision = True  # only for vision-language models; upstream errors surface loudly
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
        # Local runtimes have no meaningful static catalogue — only what the
        # user has downloaded, which is what list_models() reports.
        return []
