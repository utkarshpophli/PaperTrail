"""OpenRouter adapter — OpenAI-compatible gateway to many upstream models,
fixed host only. Its ``/models`` listing carries ``name`` and
``context_length``, which the shared listing parser already picks up."""

import httpx

from app.providers.base import ModelInfo
from app.providers.errors import InvalidConfigError
from app.providers.openai_compatible import OpenAICompatibleProvider

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# ponytail: test-scaffolding only -- see anthropic.py's DEFAULT_MODEL comment.
DEFAULT_MODEL = "openai/gpt-4o-mini"

_KNOWN_MODELS: list[ModelInfo] = [
    ModelInfo(id="openai/gpt-4o-mini", label="OpenAI: GPT-4o mini", capabilities=["generate", "stream", "vision"]),
    ModelInfo(
        id="anthropic/claude-sonnet-4.5", label="Anthropic: Claude Sonnet 4.5", capabilities=["generate", "stream", "vision"]
    ),
    ModelInfo(
        id="google/gemini-2.5-flash", label="Google: Gemini 2.5 Flash", capabilities=["generate", "stream", "vision"]
    ),
    ModelInfo(
        id="meta-llama/llama-3.3-70b-instruct", label="Meta: Llama 3.3 70B Instruct", capabilities=["generate", "stream"]
    ),
]


class OpenRouterProvider(OpenAICompatibleProvider):
    # ponytail: OpenRouter fronts embedding models too, but embed availability
    # is per-account/model and unverified here — fail loud rather than guess.
    supports_embed = False
    supports_vision = True
    supports_json_mode = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise InvalidConfigError("OpenRouter requires an api_key")
        super().__init__(base_url=_OPENROUTER_BASE_URL, model=model, api_key=api_key, transport=transport)

    def available_models(self) -> list[ModelInfo]:
        return list(_KNOWN_MODELS)
