"""Groq adapter — OpenAI-compatible ``/chat/completions`` against Groq's
hosted-inference API, known for very low latency on open-weight models."""

import httpx

from app.providers.base import ModelInfo
from app.providers.errors import InvalidConfigError
from app.providers.openai_compatible import OpenAICompatibleProvider

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# Confirmed live against this account's actual catalog (2026-09) -- the
# previous default ("llama-3.3-70b-versatile") was already absent from it.
# ponytail: test-scaffolding only -- see anthropic.py's DEFAULT_MODEL comment.
DEFAULT_MODEL = "openai/gpt-oss-20b"

# ponytail: hand-picked shortlist, not Groq's full catalogue -- same
# reasoning as nvidia_nim.py: too volatile to hardcode exhaustively. Live
# GET /providers/groq/models is the source of truth; this is only what's
# shown before that call returns.
_KNOWN_MODELS: list[ModelInfo] = [
    ModelInfo(id="openai/gpt-oss-20b", label="GPT OSS 20B", capabilities=["generate", "stream"]),
    ModelInfo(id="openai/gpt-oss-120b", label="GPT OSS 120B", capabilities=["generate", "stream"]),
    ModelInfo(id="qwen/qwen3.8-27b", label="Qwen3.8 27B", capabilities=["generate", "stream"]),
]


class GroqProvider(OpenAICompatibleProvider):
    # ponytail: Groq hosts a couple of vision-capable models but which ones
    # need a confirmed per-model allowlist we haven't built -- same stance
    # as nvidia_nim.py. Groq has no embeddings endpoint.
    supports_embed = False
    supports_vision = False
    supports_json_mode = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise InvalidConfigError("Groq requires an api_key")
        super().__init__(base_url=_GROQ_BASE_URL, model=model, api_key=api_key, transport=transport)

    def available_models(self) -> list[ModelInfo]:
        return list(_KNOWN_MODELS)
