"""Contract tests for POST /papers/upload, POST /papers/from-arxiv,
GET /papers/{id}, GET /papers/{id}/pages/{n}, DELETE /papers/{id}.

``parse_pdf`` is mocked at the ``app.papers.service`` boundary for these
tests, since document-processing-engineer's real parser
(``app.documents.parser``) is being built in parallel and may not exist (or
may not be trustworthy for a fast unit-style test) yet. This is the one
sanctioned internal-boundary mock per TESTING.md — it stands in for a
sibling module we don't own, not for our own persistence layer. Once
``app.documents.parser`` lands, add a real end-to-end test that uploads an
actual PDF fixture and asserts on real extracted text/figures, in addition
to (not instead of) these.
"""

import shutil
import uuid

import pytest
from httpx import AsyncClient

from app.core.storage import paper_dir_path

PASSWORD = "correct-horse-battery"

SAMPLE_ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <title>Attention Is All You Need</title>
    <published>2017-06-12T17:57:34Z</published>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <link href="https://arxiv.org/pdf/1706.03762v5" rel="related" type="application/pdf" title="pdf"/>
  </entry>
</feed>
"""


class _FakeFigure:
    def __init__(self, page: int, caption: str | None, image_path: str) -> None:
        self.page = page
        self.caption = caption
        self.image_path = image_path

    def model_dump(self) -> dict:
        return {"page": self.page, "caption": self.caption, "image_path": self.image_path}


class _FakePage:
    def __init__(self, number: int, text: str, figures: list[_FakeFigure]) -> None:
        self.number = number
        self.text = text
        self.figures = figures


class _FakeParsedDocument:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages


def _fake_parse_pdf(file_path: str, output_dir: str) -> _FakeParsedDocument:
    return _FakeParsedDocument(
        [_FakePage(1, "hello world", [_FakeFigure(1, "a caption", "fig-1.png")])]
    )


class _FakeArxivResponse:
    def __init__(self, text: str = "", content: bytes = b"") -> None:
        self.text = text
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeArxivStream:
    """Fakes httpx's ``async with client.stream(...) as response`` shape used
    by the real ``download_pdf`` (streaming, chunked, magic-byte-checked)."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aenter__(self) -> "_FakeArxivStream":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self, chunk_size: int):
        yield self._content


class _FakeArxivClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_FakeArxivClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, params: dict | None = None) -> _FakeArxivResponse:
        return _FakeArxivResponse(text=SAMPLE_ATOM_XML)

    def stream(self, method: str, url: str) -> _FakeArxivStream:
        return _FakeArxivStream(b"%PDF-1.4 fake pdf content")


@pytest.fixture
def mock_parse_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.papers.service.parse_pdf", _fake_parse_pdf)


@pytest.fixture
def mock_arxiv_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.papers.arxiv_client.httpx.AsyncClient", _FakeArxivClient)


async def _register_and_login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    login_response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_response.status_code == 200, login_response.text
    return login_response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_upload_succeeds_and_eventually_parses(client: AsyncClient, mock_parse_pdf: None) -> None:
    token = await _register_and_login(client, "uploader@example.com")

    response = await client.post(
        "/papers/upload",
        headers=_auth_headers(token),
        files={"file": ("paper.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
    )

    assert response.status_code == 201, response.text
    paper_id = response.json()["id"]

    # The upload response reflects the paper's state at creation time
    # ("pending") — the background parse runs and commits through a
    # separate DB session afterwards, so the updated status is only visible
    # on a subsequent read. BackgroundTasks run to completion before the
    # ASGI call returns, so a single re-GET (no polling) is enough here.
    get_response = await client.get(f"/papers/{paper_id}", headers=_auth_headers(token))
    assert get_response.json()["parse_status"] == "parsed"

    page_response = await client.get(f"/papers/{paper_id}/pages/1", headers=_auth_headers(token))
    assert page_response.status_code == 200
    page_body = page_response.json()
    assert page_body["text"] == "hello world"
    assert page_body["figures"] == [{"page": 1, "caption": "a caption", "image_path": "fig-1.png"}]


async def test_upload_rejects_non_pdf_by_magic_bytes(client: AsyncClient, mock_parse_pdf: None) -> None:
    token = await _register_and_login(client, "badupload@example.com")

    response = await client.post(
        "/papers/upload",
        headers=_auth_headers(token),
        files={"file": ("paper.pdf", b"not actually a pdf", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_file_type"


async def test_upload_marks_paper_failed_when_parsing_raises(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raising_parse_pdf(file_path: str, output_dir: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("app.papers.service.parse_pdf", _raising_parse_pdf)
    token = await _register_and_login(client, "failparse@example.com")

    response = await client.post(
        "/papers/upload",
        headers=_auth_headers(token),
        files={"file": ("paper.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
    )

    assert response.status_code == 201
    paper_id = response.json()["id"]

    get_response = await client.get(f"/papers/{paper_id}", headers=_auth_headers(token))
    assert get_response.json()["parse_status"] == "failed"
    # Sanitized, fixed message — never the raw exception text (security
    # review: str(exc) can carry file paths/library internals and this is
    # returned to the paper's owner via the API).
    assert get_response.json()["parse_error"] == "An internal error occurred while parsing this document"
    assert "boom" not in get_response.json()["parse_error"]


async def test_upload_marks_paper_failed_when_persisting_pages_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a failure during Page persistence (not just parse_pdf
    itself) used to raise outside run_parsing's try/except entirely, leaving
    the paper silently stuck in "parsing" forever with nothing logged --
    reproduced live with a NUL byte PyMuPDF embedded in extracted text
    (Postgres rejects \\x00 in a text column outright). A page with a NUL
    byte is used here to trigger a real persistence-layer failure against
    the real test Postgres, independent of app.documents.parser's own fix
    for the NUL byte itself (see tests/documents/test_parser.py)."""

    def _nul_byte_parse_pdf(file_path: str, output_dir: str) -> _FakeParsedDocument:
        return _FakeParsedDocument([_FakePage(1, "poisoned\x00text", [])])

    monkeypatch.setattr("app.papers.service.parse_pdf", _nul_byte_parse_pdf)
    token = await _register_and_login(client, "failpersist@example.com")

    response = await client.post(
        "/papers/upload",
        headers=_auth_headers(token),
        files={"file": ("paper.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
    )

    assert response.status_code == 201
    paper_id = response.json()["id"]

    get_response = await client.get(f"/papers/{paper_id}", headers=_auth_headers(token))
    assert get_response.json()["parse_status"] == "failed"
    assert get_response.json()["parse_error"] == "An internal error occurred while parsing this document"


async def test_user_cannot_get_or_delete_another_users_paper(
    client: AsyncClient, mock_parse_pdf: None
) -> None:
    token_a = await _register_and_login(client, "owner@example.com")
    token_b = await _register_and_login(client, "intruder@example.com")

    upload_response = await client.post(
        "/papers/upload",
        headers=_auth_headers(token_a),
        files={"file": ("paper.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
    )
    paper_id = upload_response.json()["id"]

    get_response = await client.get(f"/papers/{paper_id}", headers=_auth_headers(token_b))
    assert get_response.status_code == 404
    assert get_response.json()["error"]["code"] == "paper_not_found"

    delete_response = await client.delete(f"/papers/{paper_id}", headers=_auth_headers(token_b))
    assert delete_response.status_code == 404

    # owner still can
    owner_get = await client.get(f"/papers/{paper_id}", headers=_auth_headers(token_a))
    assert owner_get.status_code == 200


async def test_delete_removes_paper(client: AsyncClient, mock_parse_pdf: None) -> None:
    token = await _register_and_login(client, "deleter@example.com")
    upload_response = await client.post(
        "/papers/upload",
        headers=_auth_headers(token),
        files={"file": ("paper.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
    )
    paper_id = upload_response.json()["id"]

    delete_response = await client.delete(f"/papers/{paper_id}", headers=_auth_headers(token))
    assert delete_response.status_code == 204

    get_response = await client.get(f"/papers/{paper_id}", headers=_auth_headers(token))
    assert get_response.status_code == 404


async def test_create_from_arxiv_resolves_metadata_and_downloads_pdf(
    client: AsyncClient, mock_arxiv_http: None, mock_parse_pdf: None
) -> None:
    token = await _register_and_login(client, "arxivuser@example.com")

    response = await client.post(
        "/papers/from-arxiv",
        headers=_auth_headers(token),
        json={"arxiv_id": "1706.03762"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["arxiv_id"] == "1706.03762v5"
    assert body["title"] == "Attention Is All You Need"
    assert body["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert body["year"] == 2017

    get_response = await client.get(f"/papers/{body['id']}", headers=_auth_headers(token))
    assert get_response.json()["parse_status"] == "parsed"


async def test_from_arxiv_rejects_both_identifiers(client: AsyncClient) -> None:
    token = await _register_and_login(client, "botharxiv@example.com")

    response = await client.post(
        "/papers/from-arxiv",
        headers=_auth_headers(token),
        json={"arxiv_id": "1706.03762", "arxiv_title": "Attention Is All You Need"},
    )

    assert response.status_code == 422


async def test_download_pdf_rejects_non_arxiv_host() -> None:
    """Regression for the SSRF finding: a pdf_url pointing anywhere but
    arxiv.org/export.arxiv.org must never be fetched, even if it somehow
    ended up in a parsed Atom response (on-path tampering, a future parsing
    bug, etc.)."""
    from app.papers.arxiv_client import download_pdf
    from app.papers.exceptions import ArxivUnavailableError

    with pytest.raises(ArxivUnavailableError):
        await download_pdf("http://169.254.169.254/latest/meta-data/", "/tmp/should-not-be-written.pdf")


async def test_download_pdf_rejects_non_https() -> None:
    from app.papers.arxiv_client import download_pdf
    from app.papers.exceptions import ArxivUnavailableError

    with pytest.raises(ArxivUnavailableError):
        await download_pdf("http://arxiv.org/pdf/1706.03762v5", "/tmp/should-not-be-written.pdf")


async def test_upload_is_rate_limited_per_user(client: AsyncClient, mock_parse_pdf: None) -> None:
    token = await _register_and_login(client, "ratelimited-upload@example.com")

    responses = [
        await client.post(
            "/papers/upload",
            headers=_auth_headers(token),
            files={"file": ("paper.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        for _ in range(11)
    ]

    assert responses[-1].status_code == 429


async def test_list_papers_scoped_to_owner(client: AsyncClient, mock_parse_pdf: None) -> None:
    token_a = await _register_and_login(client, "lista@example.com")
    token_b = await _register_and_login(client, "listb@example.com")

    await client.post(
        "/papers/upload",
        headers=_auth_headers(token_a),
        files={"file": ("a.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    await client.post(
        "/papers/upload",
        headers=_auth_headers(token_b),
        files={"file": ("b.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    response_a = await client.get("/papers", headers=_auth_headers(token_a))
    assert response_a.status_code == 200
    titles_a = [p["title"] for p in response_a.json()]
    assert titles_a == ["a"]

    response_b = await client.get("/papers", headers=_auth_headers(token_b))
    titles_b = [p["title"] for p in response_b.json()]
    assert titles_b == ["b"]


async def test_get_figure_serves_bytes_and_rejects_traversal_and_non_owner(
    client: AsyncClient, mock_parse_pdf: None
) -> None:
    token = await _register_and_login(client, "figures@example.com")
    other_token = await _register_and_login(client, "figures-other@example.com")

    upload_response = await client.post(
        "/papers/upload",
        headers=_auth_headers(token),
        files={"file": ("paper.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
    )
    paper_id = upload_response.json()["id"]

    # mock_parse_pdf's _fake_parse_pdf returns a figure at "fig-1.png", but
    # doesn't actually write that file to disk — write it ourselves so the
    # happy-path assertion has real bytes to find.
    figures_dir = paper_dir_path(uuid.UUID(paper_id)) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "fig-1.png").write_bytes(b"fake-png-bytes")

    ok_response = await client.get(f"/papers/{paper_id}/figures/fig-1.png", headers=_auth_headers(token))
    assert ok_response.status_code == 200
    assert ok_response.content == b"fake-png-bytes"

    traversal_response = await client.get(
        f"/papers/{paper_id}/figures/..%2f..%2fsource.pdf", headers=_auth_headers(token)
    )
    assert traversal_response.status_code in (403, 404)

    missing_response = await client.get(f"/papers/{paper_id}/figures/nope.png", headers=_auth_headers(token))
    assert missing_response.status_code == 404

    other_response = await client.get(f"/papers/{paper_id}/figures/fig-1.png", headers=_auth_headers(other_token))
    assert other_response.status_code == 404

    shutil.rmtree(figures_dir.parent, ignore_errors=True)


async def test_from_arxiv_is_rate_limited_per_user(
    client: AsyncClient, mock_arxiv_http: None, mock_parse_pdf: None
) -> None:
    token = await _register_and_login(client, "ratelimited-arxiv@example.com")

    responses = [
        await client.post(
            "/papers/from-arxiv",
            headers=_auth_headers(token),
            json={"arxiv_id": "1706.03762"},
        )
        for _ in range(11)
    ]

    assert responses[-1].status_code == 429
