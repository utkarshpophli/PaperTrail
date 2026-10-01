"""Unit tests for ``app.coderesearch.github_client`` -- URL host-allowlist
rejection (``parse_github_url``), and metadata/search/README fetches against
a fake ``httpx.AsyncClient`` (never a live call to GitHub's API, per
TESTING.md), same monkeypatch-the-module's-``httpx.AsyncClient`` pattern as
``tests/discovery/test_arxiv_search.py``.
"""

import base64

import httpx
import pytest

from app.coderesearch.exceptions import GithubNotFoundError, GithubUnavailableError, InvalidRepositoryUrlError
from app.coderesearch.github_client import (
    fetch_readme,
    fetch_repo_metadata,
    parse_github_url,
    search_repos_by_query,
)


class _FakeResponse:
    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> object:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=httpx.Request("GET", "https://api.github.com/"), response=httpx.Response(self.status_code))


class _FakeClient:
    last_headers: dict | None = None
    last_params: dict | None = None
    last_url: str | None = None

    def __init__(self, status_code: int = 200, body: object | None = None, *, raise_timeout: bool = False) -> None:
        self._status_code = status_code
        self._body = body
        self._raise_timeout = raise_timeout

    def __call__(self, *args: object, **kwargs: object) -> "_FakeClient":
        return self

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> _FakeResponse:
        _FakeClient.last_headers = headers
        _FakeClient.last_params = params
        _FakeClient.last_url = url
        if self._raise_timeout:
            raise httpx.TimeoutException("timed out")
        return _FakeResponse(self._status_code, self._body)


# ---- parse_github_url -------------------------------------------------


def test_parse_github_url_accepts_valid_repo_url() -> None:
    assert parse_github_url("https://github.com/openai/gpt-3") == ("openai", "gpt-3")


def test_parse_github_url_accepts_trailing_slash_and_dot_git() -> None:
    assert parse_github_url("https://github.com/openai/gpt-3.git") == ("openai", "gpt-3")
    assert parse_github_url("https://github.com/openai/gpt-3/") == ("openai", "gpt-3")


def test_parse_github_url_rejects_non_github_host() -> None:
    """The host-allowlist rejection case -- a URL claiming to be a GitHub
    repo but pointing elsewhere must never be trusted (SSRF-adjacent
    discipline, same as arxiv_client's PDF host allowlist)."""
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_url("https://evil.example.com/openai/gpt-3")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com.evil.com/openai/gpt-3",  # subdomain-suffix confusion
        "https://github.com@evil.com/openai/gpt-3",  # userinfo confusion
        "https://evil.com/github.com/openai/gpt-3",  # path-prefix confusion
    ],
)
def test_parse_github_url_rejects_host_confusion_bypasses(url: str) -> None:
    """Regression test for classic allowlist-bypass shapes -- exact ``host ==
    "github.com"`` equality (not substring/prefix matching) must reject all
    three, same discipline the module docstring claims but that wasn't
    previously pinned down by a test."""
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_url(url)


def test_parse_github_url_rejects_non_https_scheme() -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_url("http://github.com/openai/gpt-3")


def test_parse_github_url_rejects_malformed_path() -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_url("https://github.com/openai")


# ---- fetch_repo_metadata ------------------------------------------------


async def test_fetch_repo_metadata_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {
        "owner": {"login": "openai"},
        "name": "gpt-3",
        "description": "GPT-3 paper code",
        "stargazers_count": 1000,
        "html_url": "https://github.com/openai/gpt-3",
    }
    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", _FakeClient(200, body))

    metadata = await fetch_repo_metadata("openai", "gpt-3", None)

    assert metadata.owner == "openai"
    assert metadata.name == "gpt-3"
    assert metadata.stars == 1000


async def test_fetch_repo_metadata_sends_token_as_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"owner": {"login": "openai"}, "name": "gpt-3", "html_url": "https://github.com/openai/gpt-3"}
    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", _FakeClient(200, body))

    await fetch_repo_metadata("openai", "gpt-3", "my-token")

    assert _FakeClient.last_headers["Authorization"] == "Bearer my-token"


async def test_fetch_repo_metadata_never_requires_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"owner": {"login": "openai"}, "name": "gpt-3", "html_url": "https://github.com/openai/gpt-3"}
    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", _FakeClient(200, body))

    await fetch_repo_metadata("openai", "gpt-3", None)

    assert "Authorization" not in _FakeClient.last_headers


async def test_fetch_repo_metadata_raises_not_found_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", _FakeClient(404, {}))

    with pytest.raises(GithubNotFoundError):
        await fetch_repo_metadata("nobody", "nothing", None)


async def test_fetch_repo_metadata_raises_unavailable_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", _FakeClient(raise_timeout=True))

    with pytest.raises(GithubUnavailableError):
        await fetch_repo_metadata("openai", "gpt-3", None)


# ---- search_repos_by_query ----------------------------------------------


async def test_search_repos_by_query_parses_items(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {
        "items": [
            {"owner": {"login": "openai"}, "name": "gpt-3", "stargazers_count": 5, "html_url": "u1", "description": "d1"}
        ]
    }
    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", _FakeClient(200, body))

    results = await search_repos_by_query('"GPT-3"', None)

    assert len(results) == 1
    assert results[0].owner == "openai"


async def test_search_repos_by_query_returns_empty_list_for_zero_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", _FakeClient(200, {"items": []}))

    results = await search_repos_by_query("an extremely obscure paper title", None)

    assert results == []


# ---- fetch_readme ---------------------------------------------------------


async def test_fetch_readme_decodes_base64_content(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "# My Project\nSetup instructions here."
    body = {"content": base64.b64encode(raw.encode("utf-8")).decode("ascii"), "encoding": "base64"}
    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", _FakeClient(200, body))

    text = await fetch_readme("openai", "gpt-3", None)

    assert text == raw


async def test_fetch_readme_raises_not_found_when_repo_has_no_readme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.coderesearch.github_client.httpx.AsyncClient", _FakeClient(404, {}))

    with pytest.raises(GithubNotFoundError):
        await fetch_readme("openai", "gpt-3", None)
