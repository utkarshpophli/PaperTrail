"""Loopback-only validation shared by every local runtime (Ollama, llama.cpp,
LM Studio, ...). An SSRF control (SECURITY.md), not a formality: it runs at
provider construction, before any HTTP request is attempted.
"""

import httpx

from app.core.config import get_settings
from app.providers.errors import InvalidConfigError

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def validate_loopback_endpoint(endpoint: str) -> str:
    """Raises ``InvalidConfigError`` for anything but 127.0.0.1/localhost/::1,
    and for every endpoint when local providers are disabled on this server."""
    if not get_settings().local_providers_enabled:
        raise InvalidConfigError(
            "Local model providers are disabled on this server (shared hosted demo). "
            "Run Paper Trail on your own machine to use Ollama, LM Studio or llama.cpp."
        )
    try:
        parsed = httpx.URL(endpoint)
    except httpx.InvalidURL as exc:
        raise InvalidConfigError(f"Invalid local provider endpoint URL: {endpoint!r}") from exc

    if parsed.scheme not in ("http", "https") or not parsed.host or parsed.host.lower() not in _LOOPBACK_HOSTS:
        raise InvalidConfigError(
            f"Refusing non-loopback local provider endpoint {endpoint!r}: "
            "only 127.0.0.1, localhost, or ::1 are allowed for local providers"
        )
    return endpoint


def openai_base_url(endpoint: str) -> str:
    """``http://localhost:1234`` and ``http://localhost:1234/v1`` both map to
    the OpenAI-compatible ``.../v1`` root, so users can paste either."""
    root = endpoint.rstrip("/")
    return root if root.endswith("/v1") else f"{root}/v1"
