"""Provider catalog metadata + provider construction.

Implemented adapters: Google Gemini (``google``), OpenAI (``openai``),
Anthropic (``anthropic``), OpenRouter (``openrouter``), Groq (``groq``),
NVIDIA NIM (``nvidia_nim``), and the local runtimes Ollama (``ollama``), LM
Studio (``lmstudio``) and llama.cpp (``llama_cpp``). Unsloth Studio remains
catalogued but deferred; ``build_provider`` raises ``NotImplementedError`` for
it rather than pretending it works.

Kept ``ProviderCatalogEntry``'s shape and ``ProviderNotFoundError`` (from
``app.providers.exceptions``) exactly as backend-engineer defined them —
``app.providers.router`` and its tests depend on both.
"""

from typing import Any, Literal

from pydantic import BaseModel

from app.providers.anthropic import AnthropicProvider
from app.providers.errors import InvalidConfigError
from app.providers.exceptions import ProviderNotFoundError
from app.providers.gemini import GeminiProvider
from app.providers.groq import GroqProvider
from app.providers.llama_cpp import LlamaCppProvider
from app.providers.lmstudio import LMStudioProvider
from app.providers.nvidia_nim import NvidiaNimProvider
from app.providers.ollama import OllamaProvider
from app.providers.openai import OpenAIProvider
from app.providers.openrouter import OpenRouterProvider


class ProviderCatalogEntry(BaseModel):
    id: str
    label: str
    auth: Literal["api_key", "none"]
    capabilities: list[str]
    # Derived from _IMPLEMENTED_IDS below at catalog-construction time so the
    # frontend never needs its own hand-mirrored copy of that set (a real
    # gap flagged during Phase 3 review — this closes it).
    implemented: bool = True


_IMPLEMENTED_IDS = {"google", "openai", "anthropic", "openrouter", "groq", "nvidia_nim", "ollama", "lmstudio", "llama_cpp"}


def _entry(id: str, label: str, auth: Literal["api_key", "none"], capabilities: list[str]) -> ProviderCatalogEntry:
    return ProviderCatalogEntry(id=id, label=label, auth=auth, capabilities=capabilities, implemented=id in _IMPLEMENTED_IDS)


_CATALOG: list[ProviderCatalogEntry] = [
    _entry("google", "Google Gemini", "api_key", ["generate", "stream", "embed", "vision"]),
    _entry("openai", "OpenAI", "api_key", ["generate", "stream", "embed", "vision"]),
    _entry("anthropic", "Anthropic", "api_key", ["generate", "stream", "vision"]),
    _entry("openrouter", "OpenRouter", "api_key", ["generate", "stream", "vision"]),
    _entry("groq", "Groq", "api_key", ["generate", "stream"]),
    _entry("ollama", "Ollama", "none", ["generate", "stream", "embed", "vision"]),
    _entry("lmstudio", "LM Studio", "none", ["generate", "stream", "embed", "vision"]),
    _entry("llama_cpp", "llama.cpp", "none", ["generate", "stream"]),
    _entry("unsloth_studio", "Unsloth Studio", "none", ["generate", "stream"]),
    _entry("nvidia_nim", "NVIDIA NIM", "api_key", ["generate", "stream", "embed"]),
]


def describe_provider(provider_id: str) -> str:
    """"NVIDIA NIM (cloud API)" / "Ollama (on this machine)" -- every no-key
    provider in the catalog is a loopback-only local runtime."""
    entry = next((e for e in _CATALOG if e.id == provider_id), None)
    if entry is None:
        return provider_id
    return f"{entry.label} ({'on this machine' if entry.auth == 'none' else 'cloud API'})"


def list_provider_catalog() -> list[ProviderCatalogEntry]:
    return list(_CATALOG)


def build_provider(provider_id: str, *, api_key: str | None = None, endpoint: str | None = None) -> Any:
    """Constructs a provider instance for a single request/call — never
    cached, never persisted. Raises ``ProviderNotFoundError`` for an unknown
    id. For ``ollama``, ``endpoint`` is required and is where loopback
    validation happens (``OllamaProvider.__init__`` calls
    ``validate_loopback_endpoint`` immediately) — this raises before any
    request is attempted, never deferred to first use.

    Deliberately takes no ``model`` — every adapter requires one per call via
    ``generate``/``stream``'s ``model=`` opt (``app.providers.base.
    require_model``), never silently substituting its own default. The
    adapter constructor's own ``model: str = DEFAULT_MODEL`` parameter is
    test-scaffolding only at this point (many unit tests construct a
    provider directly); production code never reaches it because it's never
    passed here and can never reach an actual HTTP request either way.
    """
    if not any(entry.id == provider_id for entry in _CATALOG):
        raise ProviderNotFoundError(f"Unknown provider '{provider_id}'")

    if provider_id not in _IMPLEMENTED_IDS:
        raise NotImplementedError(f"Provider adapter construction for '{provider_id}' is not implemented yet")

    entry = next(e for e in _CATALOG if e.id == provider_id)
    if entry.auth == "api_key":
        if not api_key:
            raise InvalidConfigError(f"{entry.label} requires an api_key")
        if provider_id == "google":
            return GeminiProvider(api_key=api_key)
        if provider_id == "openai":
            return OpenAIProvider(api_key=api_key)
        if provider_id == "anthropic":
            return AnthropicProvider(api_key=api_key)
        if provider_id == "openrouter":
            return OpenRouterProvider(api_key=api_key)
        if provider_id == "groq":
            return GroqProvider(api_key=api_key)
        return NvidiaNimProvider(api_key=api_key)  # nvidia_nim

    if not endpoint:
        raise InvalidConfigError(f"{entry.label} requires an endpoint")
    # Every local adapter validates the endpoint as loopback-only in __init__.
    if provider_id == "lmstudio":
        return LMStudioProvider(endpoint=endpoint)
    if provider_id == "llama_cpp":
        return LlamaCppProvider(endpoint=endpoint)
    return OllamaProvider(endpoint=endpoint)  # ollama
