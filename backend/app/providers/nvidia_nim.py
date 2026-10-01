"""NVIDIA NIM adapter — OpenAI-compatible ``/chat/completions`` against
build.nvidia.com's integrate endpoint (AI_PROVIDERS.md).

NIM's full catalogue is too large/volatile to hardcode (per AI_PROVIDERS.md),
so ``available_models`` surfaces a short hand-picked free-tier shortlist as
suggestions; any other model id is still accepted freeform by simply passing
it as ``model``/``opts["model"]`` — no allowlist blocks it.
"""

import httpx

from app.providers.base import ModelInfo
from app.providers.errors import InvalidConfigError
from app.providers.openai_compatible import OpenAICompatibleProvider

_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
# NIM's own catalogue turns over fast enough that a hardcoded id here is a
# liability, not a convenience — confirmed live: the previous default
# ("meta/llama-3.1-8b-instruct") started returning 410 Gone from NVIDIA
# without any change on our side, and NVIDIA's own developer forum has
# reports of GET /v1/models listing a model that then 404s/500s on
# /chat/completions.
# ponytail: test-scaffolding only -- registry.build_provider() no longer
# passes this at construction, and require_model() blocks any call that
# omits an explicit model, so it can never reach a real request in
# production (the picker also always auto-selects a live-listed model).
# Revisit whenever it's next found dead in a test fixture; there is no way
# to keep it perpetually current without querying NIM's catalogue live.
DEFAULT_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
_DEFAULT_EMBED_MODEL = "nvidia/nv-embedqa-e5-v5"

# ponytail: hand-picked shortlist of NIM's free-tier catalogue as of
# 2026-09, not the full catalogue — too large/volatile to hardcode per
# AI_PROVIDERS.md. Freeform model ids outside this list still work; this
# list is a UI suggestion, not an allowlist, and per the DEFAULT_MODEL note
# above it WILL go stale — the live /providers/{id}/models listing is the
# source of truth, this is only what's shown before that call returns.
_FREE_TIER_MODELS: list[ModelInfo] = [
    ModelInfo(
        id="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        label="Nemotron 3 Nano Omni 30B (free tier)",
        capabilities=["generate", "stream"],
    ),
    ModelInfo(
        id="nvidia/nemotron-3-super-120b-a12b",
        label="Nemotron 3 Super 120B (free tier)",
        capabilities=["generate", "stream"],
    ),
    ModelInfo(id="z-ai/glm-5.1", label="GLM 5.1 (free tier)", capabilities=["generate", "stream"]),
    ModelInfo(id=_DEFAULT_EMBED_MODEL, label="NV-EmbedQA E5 v5 (free tier)", capabilities=["embed"]),
]


class NvidiaNimProvider(OpenAICompatibleProvider):
    # ponytail: NIM does host vision-capable models, but which ones need a
    # confirmed per-model allowlist we haven't built yet — failing loud here
    # beats guessing a model supports vision. Flip to True once that
    # allowlist exists.
    supports_vision = False
    supports_embed = True
    # NIM's retrieval embedders (nv-embedqa-*) require an explicit input_type
    # -- confirmed live, previously untested since embed_model was always a
    # constructor-time default that no test call ever reached for real.
    # ponytail: symmetric "passage" for every call (queries and documents
    # alike) is a simplification -- split query vs. passage input_type if
    # ranking quality ever measurably needs it.
    _embed_extra_body = {"input_type": "passage", "truncate": "END"}

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise InvalidConfigError("NVIDIA NIM requires an api_key")
        # NVIDIA NIM's documented free-tier cap is 40 requests/minute per
        # account; throttled proactively here rather than only reacting to
        # 429s, since a single /analyze call fans out several parallel
        # requests per stage across 4 stages.
        super().__init__(
            base_url=_NIM_BASE_URL,
            model=model,
            api_key=api_key,
            transport=transport,
            requests_per_minute=40,
        )

    def available_models(self) -> list[ModelInfo]:
        return list(_FREE_TIER_MODELS)
