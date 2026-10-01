"""Tests for the provider registry — the exact contract the Providers API
(backend-engineer's ``app.providers.router``) is built against."""

import pytest

from app.providers.errors import InvalidConfigError
from app.providers.exceptions import ProviderNotFoundError
from app.providers.gemini import GeminiProvider
from app.providers.nvidia_nim import NvidiaNimProvider
from app.providers.ollama import OllamaProvider
from app.providers.registry import build_provider, list_provider_catalog


def test_unknown_provider_id_raises_provider_not_found_error() -> None:
    with pytest.raises(ProviderNotFoundError):
        build_provider("does-not-exist")


def test_deferred_provider_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        build_provider("unsloth_studio", endpoint="http://127.0.0.1:8888")


def test_build_google_requires_api_key() -> None:
    with pytest.raises(InvalidConfigError):
        build_provider("google")


def test_build_google_returns_gemini_provider() -> None:
    provider = build_provider("google", api_key="test-key")
    assert isinstance(provider, GeminiProvider)


def test_build_nvidia_nim_requires_api_key() -> None:
    with pytest.raises(InvalidConfigError):
        build_provider("nvidia_nim")


def test_build_nvidia_nim_returns_provider() -> None:
    provider = build_provider("nvidia_nim", api_key="nvapi-test")
    assert isinstance(provider, NvidiaNimProvider)


def test_build_ollama_requires_endpoint() -> None:
    with pytest.raises(InvalidConfigError):
        build_provider("ollama")


def test_build_ollama_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(InvalidConfigError):
        build_provider("ollama", endpoint="http://8.8.8.8:11434")


def test_build_ollama_returns_provider_for_loopback_endpoint() -> None:
    provider = build_provider("ollama", endpoint="http://127.0.0.1:11434")
    assert isinstance(provider, OllamaProvider)


def test_catalog_capabilities_reflect_implemented_adapters() -> None:
    catalog = {entry.id: entry for entry in list_provider_catalog()}

    assert set(catalog["google"].capabilities) == {"generate", "stream", "embed", "vision"}
    assert set(catalog["ollama"].capabilities) == {"generate", "stream", "embed", "vision"}
    assert set(catalog["nvidia_nim"].capabilities) == {"generate", "stream", "embed"}


def test_new_providers_are_built_and_marked_implemented() -> None:
    from app.providers.anthropic import AnthropicProvider
    from app.providers.groq import GroqProvider
    from app.providers.llama_cpp import LlamaCppProvider
    from app.providers.lmstudio import LMStudioProvider
    from app.providers.openai import OpenAIProvider
    from app.providers.openrouter import OpenRouterProvider

    assert isinstance(build_provider("openai", api_key="sk-test"), OpenAIProvider)
    assert isinstance(build_provider("anthropic", api_key="sk-ant-test"), AnthropicProvider)
    assert isinstance(build_provider("openrouter", api_key="sk-or-test"), OpenRouterProvider)
    assert isinstance(build_provider("groq", api_key="gsk-test"), GroqProvider)
    assert isinstance(build_provider("lmstudio", endpoint="http://localhost:1234"), LMStudioProvider)
    assert isinstance(build_provider("llama_cpp", endpoint="http://localhost:8080"), LlamaCppProvider)

    catalog = {entry.id: entry for entry in list_provider_catalog()}
    for provider_id in (
        "openai",
        "anthropic",
        "openrouter",
        "groq",
        "lmstudio",
        "llama_cpp",
        "google",
        "nvidia_nim",
        "ollama",
    ):
        assert catalog[provider_id].implemented, provider_id
    assert not catalog["unsloth_studio"].implemented
    assert catalog["lmstudio"].auth == "none" and catalog["llama_cpp"].auth == "none"


@pytest.mark.parametrize("provider_id", ["openai", "anthropic", "openrouter", "groq"])
def test_cloud_providers_require_api_key(provider_id: str) -> None:
    with pytest.raises(InvalidConfigError):
        build_provider(provider_id)


@pytest.mark.parametrize("provider_id", ["lmstudio", "llama_cpp"])
def test_local_providers_require_loopback_endpoint(provider_id: str) -> None:
    with pytest.raises(InvalidConfigError):
        build_provider(provider_id)
    with pytest.raises(InvalidConfigError):
        build_provider(provider_id, endpoint="http://8.8.8.8:1234")
