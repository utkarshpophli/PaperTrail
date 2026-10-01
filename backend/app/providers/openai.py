"""OpenAI adapter — the reference OpenAI-compatible API, fixed host only
(no user-supplied base URL: an api_key provider never accepts an endpoint)."""

import httpx

from app.providers.base import ModelInfo
from app.providers.errors import InvalidConfigError
from app.providers.openai_compatible import OpenAICompatibleProvider

_OPENAI_BASE_URL = "https://api.openai.com/v1"
# ponytail: test-scaffolding only -- see anthropic.py's DEFAULT_MODEL comment.
DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_EMBED_MODEL = "text-embedding-3-small"

# Fallback suggestions only — the live /models listing is the source of truth
# and any freeform model id is accepted.
_KNOWN_MODELS: list[ModelInfo] = [
    ModelInfo(id="gpt-4o", label="GPT-4o", capabilities=["generate", "stream", "vision"]),
    ModelInfo(id="gpt-4o-mini", label="GPT-4o mini", capabilities=["generate", "stream", "vision"]),
    ModelInfo(id="gpt-4.1", label="GPT-4.1", capabilities=["generate", "stream", "vision"]),
    ModelInfo(id="gpt-4.1-mini", label="GPT-4.1 mini", capabilities=["generate", "stream", "vision"]),
    ModelInfo(id=_DEFAULT_EMBED_MODEL, label="Text Embedding 3 Small", capabilities=["embed"]),
]


class OpenAIProvider(OpenAICompatibleProvider):
    supports_embed = True
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
            raise InvalidConfigError("OpenAI requires an api_key")
        super().__init__(base_url=_OPENAI_BASE_URL, model=model, api_key=api_key, transport=transport)

    def available_models(self) -> list[ModelInfo]:
        return list(_KNOWN_MODELS)
