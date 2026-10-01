"""Loopback discipline is identical for every local runtime (SECURITY.md SSRF control)."""

import httpx
import pytest

from app.providers.errors import InvalidConfigError
from app.providers.llama_cpp import LlamaCppProvider
from app.providers.lmstudio import LMStudioProvider
from app.providers.local_endpoint import openai_base_url
from app.providers.ollama import OllamaProvider

LOCAL = [LMStudioProvider, LlamaCppProvider, OllamaProvider]


def _fail_if_called(request: httpx.Request) -> httpx.Response:  # pragma: no cover - assertion path
    raise AssertionError(f"no HTTP request should have been attempted, got {request.url}")


@pytest.mark.parametrize("cls", LOCAL)
@pytest.mark.parametrize(
    "bad",
    [
        "http://8.8.8.8:1234",
        "http://10.0.0.5:8080",
        "http://192.168.1.10:1234",
        "http://internal.corp:8080",
        "http://localhost.evil.com:1234",
        "http://localhost@evil.com:1234",
        "ftp://localhost:1234",
        "not a url",
    ],
)
def test_non_loopback_rejected_before_any_request(cls: type, bad: str) -> None:
    with pytest.raises(InvalidConfigError):
        cls(endpoint=bad, transport=httpx.MockTransport(_fail_if_called))


@pytest.mark.parametrize("cls", LOCAL)
@pytest.mark.parametrize("good", ["http://127.0.0.1:1234", "http://localhost:1234", "http://[::1]:1234"])
def test_loopback_accepted(cls: type, good: str) -> None:
    cls(endpoint=good)


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("http://localhost:1234", "http://localhost:1234/v1"),
        ("http://localhost:1234/", "http://localhost:1234/v1"),
        ("http://localhost:1234/v1", "http://localhost:1234/v1"),
        ("http://localhost:1234/v1/", "http://localhost:1234/v1"),
    ],
)
def test_openai_base_url_appends_v1_once(endpoint: str, expected: str) -> None:
    assert openai_base_url(endpoint) == expected


@pytest.fixture
def local_providers_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "local_providers_enabled", False)


@pytest.mark.parametrize("cls", LOCAL)
def test_local_providers_refused_when_disabled_on_a_shared_server(cls: type, local_providers_disabled: None) -> None:
    # On a hosted demo, "loopback" is the server's own services, not the
    # visitor's machine: even a valid loopback endpoint must be refused.
    with pytest.raises(InvalidConfigError, match="disabled on this server"):
        cls(endpoint="http://localhost:11434")


def test_catalog_hides_local_providers_when_disabled(local_providers_disabled: None) -> None:
    from app.providers.registry import list_provider_catalog

    catalog = list_provider_catalog()
    assert catalog, "cloud providers must still be listed"
    assert all(entry.auth != "none" for entry in catalog)
