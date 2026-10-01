"""Unit tests for ``app.graph.openalex_client`` against a fake
``httpx.AsyncClient`` (never a live OpenAlex call, per TESTING.md) -- same
monkeypatch pattern as ``tests/coderesearch/test_github_client.py``.
"""

import httpx
import pytest

from app.graph import openalex_client
from app.graph.exceptions import OpenAlexUnavailableError
from app.graph.openalex_client import resolve_openalex_work


class _FakeResponse:
    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> object:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("GET", "https://api.openalex.org/"), response=httpx.Response(self.status_code)
            )


class _FakeClient:
    last_url: str | None = None
    last_params: dict | None = None

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

    async def get(self, url: str, params: dict | None = None) -> _FakeResponse:
        _FakeClient.last_url = url
        _FakeClient.last_params = params
        if self._raise_timeout:
            raise httpx.TimeoutException("timed out")
        return _FakeResponse(self._status_code, self._body)


def _patch(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    monkeypatch.setattr("app.graph.openalex_client.httpx.AsyncClient", client)


async def test_resolve_by_doi_parses_work(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"id": "https://openalex.org/W1", "referenced_works": ["https://openalex.org/W2", "https://openalex.org/W3"]}
    _patch(monkeypatch, _FakeClient(200, body))

    work = await resolve_openalex_work(doi="10.1234/abc", title="ignored when doi given")

    assert work is not None
    assert work.openalex_id == "https://openalex.org/W1"
    assert work.referenced_works == ["https://openalex.org/W2", "https://openalex.org/W3"]
    assert _FakeClient.last_url == "https://api.openalex.org/works/doi:10.1234/abc"


async def test_resolve_by_doi_strips_url_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient(200, {"id": "W1", "referenced_works": []}))

    await resolve_openalex_work(doi="https://doi.org/10.1234/abc")

    assert _FakeClient.last_url == "https://api.openalex.org/works/doi:10.1234/abc"


async def test_resolve_by_doi_404_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient(404, {}))

    assert await resolve_openalex_work(doi="10.0000/missing") is None


async def test_resolve_falls_back_to_title_search(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {
        "results": [
            {"id": "https://openalex.org/W9", "display_name": "Attention Is All You Need", "referenced_works": ["https://openalex.org/W1"]}
        ]
    }
    _patch(monkeypatch, _FakeClient(200, body))

    work = await resolve_openalex_work(title="Attention Is All You Need")

    assert work is not None
    assert work.openalex_id == "https://openalex.org/W9"
    assert _FakeClient.last_url == "https://api.openalex.org/works"
    assert _FakeClient.last_params is not None
    assert _FakeClient.last_params["search"] == "Attention Is All You Need"
    assert _FakeClient.last_params["per_page"] == "5"


async def test_resolve_title_no_results_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient(200, {"results": []}))

    assert await resolve_openalex_work(title="a paper nobody indexed") is None


async def test_resolve_with_neither_identifier_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient(200, {}))

    assert await resolve_openalex_work() is None


async def test_resolve_handles_missing_referenced_works(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient(200, {"id": "W1", "referenced_works": None}))

    work = await resolve_openalex_work(doi="10.1/x")

    assert work is not None
    assert work.referenced_works == []


async def test_timeout_raises_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient(raise_timeout=True))

    with pytest.raises(OpenAlexUnavailableError):
        await resolve_openalex_work(doi="10.1/x")


async def test_http_error_raises_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient(500, {}))

    with pytest.raises(OpenAlexUnavailableError):
        await resolve_openalex_work(title="anything")


async def test_requests_only_go_to_allowlisted_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient(200, {"id": "W1", "referenced_works": []}))

    await resolve_openalex_work(doi="10.1/x")
    assert _FakeClient.last_url is not None
    assert httpx.URL(_FakeClient.last_url).host in openalex_client._ALLOWED_HOSTS

    await resolve_openalex_work(title="t")
    assert httpx.URL(_FakeClient.last_url).host in openalex_client._ALLOWED_HOSTS


async def test_mailto_sent_only_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient(200, {"results": []}))
    monkeypatch.setattr(openalex_client.get_settings(), "openalex_contact_email", None)
    await resolve_openalex_work(title="t")
    assert _FakeClient.last_params is not None
    assert "mailto" not in _FakeClient.last_params

    monkeypatch.setattr(openalex_client.get_settings(), "openalex_contact_email", "me@example.com")
    await resolve_openalex_work(title="t")
    assert _FakeClient.last_params["mailto"] == "me@example.com"


@pytest.mark.parametrize(
    "hostile_doi",
    ["10.1/../../authors", "10.1/x/..", "../etc/passwd", "10.1/x y", "https://evil.example/10.1/x"],
)
async def test_hostile_doi_never_reaches_the_url_path(monkeypatch: pytest.MonkeyPatch, hostile_doi: str) -> None:
    _patch(monkeypatch, _FakeClient(200, {"results": []}))
    _FakeClient.last_url = None

    await resolve_openalex_work(doi=hostile_doi, title="Some Title")

    # Rejected DOI -> falls back to the title search; the crafted string is
    # never interpolated into a URL.
    assert _FakeClient.last_url == "https://api.openalex.org/works"


@pytest.mark.parametrize("doi", ["10.1/x?select=id", "10.1/x#frag", "10.1002/(SICI)1097-4571%3F#x"])
async def test_doi_special_characters_are_percent_encoded(monkeypatch: pytest.MonkeyPatch, doi: str) -> None:
    _patch(monkeypatch, _FakeClient(200, {"id": "W1", "referenced_works": []}))

    await resolve_openalex_work(doi=doi)

    url = httpx.URL(_FakeClient.last_url or "")
    assert url.host == "api.openalex.org"
    assert "?" not in (_FakeClient.last_url or "")
    assert "#" not in (_FakeClient.last_url or "")


async def test_title_search_rejects_non_matching_top_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"results": [{"id": "W_WRONG", "display_name": "A Completely Different Paper", "referenced_works": ["W1"]}]}
    _patch(monkeypatch, _FakeClient(200, body))

    assert await resolve_openalex_work(title="Attention Is All You Need") is None
