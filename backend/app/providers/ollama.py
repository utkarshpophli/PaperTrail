"""Ollama adapter — local, no auth, loopback-only.

Follows the same host-validation discipline already established in
``app.papers.arxiv_client`` (allowlist-before-fetch, not "trust then catch"):
a non-loopback endpoint is rejected the moment it's given to this module,
before any HTTP request is attempted (SECURITY.md's SSRF control).

Ollama exposes both its native API (``/api/*``) and an OpenAI-compatible
``/v1/*`` surface; this adapter uses ``/v1`` for generate/stream/embed/vision
(via ``OpenAICompatibleProvider``) and the native ``/api/tags``/``/api/show``
for model listing and per-model capability discovery, since the OpenAI-
compatible surface doesn't expose either.
"""

import httpx

from app.core.logging import get_logger
from app.providers.base import LiveModel, ModelInfo
from app.providers.errors import NotSupportedError, ProviderUnavailableError
from app.providers.local_endpoint import validate_loopback_endpoint
from app.providers.model_kinds import classify_model_id
from app.providers.openai_compatible import OpenAICompatibleProvider

logger = get_logger(__name__)

# ponytail: test-scaffolding only -- see anthropic.py's DEFAULT_MODEL comment.
DEFAULT_MODEL = "llama3.1"


class OllamaProvider(OpenAICompatibleProvider):
    # embed/vision support genuinely varies per locally-installed model
    # (a plain text chat model can't embed or see images) — never assumed
    # true; ``_require_capability`` confirms it against the running Ollama
    # instance before every embed/vision call.
    supports_embed = True
    supports_vision = True
    supports_json_mode = False

    def __init__(
        self,
        *,
        endpoint: str,
        model: str = DEFAULT_MODEL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        validate_loopback_endpoint(endpoint)
        self._native_base_url = endpoint.rstrip("/")
        super().__init__(base_url=f"{self._native_base_url}/v1", model=model, api_key=None, transport=transport)

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        await self._require_capability("embedding", model)
        return await super().embed(texts, model=model)

    async def vision(self, image: bytes, prompt: str) -> str:
        await self._require_capability("vision", self._model)
        return await super().vision(image, prompt)

    def available_models(self) -> list[ModelInfo]:
        # Loopback-only by construction, so this blocking call is a
        # sub-millisecond local round trip, not a real "sync I/O in a sync
        # method" concern the way a cloud call would be.
        try:
            with httpx.Client(timeout=5.0, transport=self._transport) as client:
                response = client.get(f"{self._native_base_url}/api/tags")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Could not list models from Ollama at {self._native_base_url}: {exc}") from exc

        return [
            ModelInfo(id=entry["name"], label=entry["name"], capabilities=["generate", "stream"])
            for entry in response.json().get("models", [])
        ]

    async def list_models(self) -> list[LiveModel]:
        data = await self._get(f"{self._native_base_url}/api/tags")
        try:
            names = [entry["name"] for entry in data.get("models", []) if isinstance(entry.get("name"), str)]
        except (TypeError, AttributeError) as exc:
            raise ProviderUnavailableError("Unexpected Ollama /api/tags response shape") from exc
        return [LiveModel(id=name, label=name, kind=classify_model_id(name)) for name in names]

    async def _require_capability(self, capability: str, model: str) -> None:
        capabilities = await self._fetch_capabilities(model)
        if capability not in capabilities:
            raise NotSupportedError(
                f"Ollama model '{model}' does not report '{capability}' capability "
                f"(reported: {sorted(capabilities) or 'none'})"
            )

    async def _fetch_capabilities(self, model: str) -> set[str]:
        async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
            try:
                response = await client.post(f"{self._native_base_url}/api/show", json={"model": model})
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(
                    f"Could not reach Ollama at {self._native_base_url} to check model capabilities"
                ) from exc

        if response.status_code == 404:
            raise ProviderUnavailableError(f"Ollama model '{model}' not found")
        if response.status_code >= 400:
            # Never echo the probed endpoint's response body back to the
            # caller (security review: SSRF-to-service-enumeration surface).
            logger.warning("ollama_show_failed status=%s body=%s", response.status_code, response.text[:500])
            raise ProviderUnavailableError(f"Ollama /api/show failed ({response.status_code})")

        return set(response.json().get("capabilities", []))
