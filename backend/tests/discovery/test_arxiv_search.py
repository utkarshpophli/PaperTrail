"""Unit tests for ``app.papers.arxiv_client.search_arxiv_topic`` -- the
Phase 5 multi-result arXiv query, added alongside the existing single-result
``resolve_arxiv_metadata``.
"""

import pytest

from app.papers.arxiv_client import search_arxiv_topic
from app.papers.exceptions import ArxivUnavailableError

MULTI_ENTRY_ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <title>Attention Is All You Need</title>
    <summary>
      We propose a new simple network architecture, the Transformer.
    </summary>
    <published>2017-06-12T17:57:34Z</published>
    <author><name>Ashish Vaswani</name></author>
    <link href="https://arxiv.org/pdf/1706.03762v5" rel="related" type="application/pdf" title="pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/1810.04805v2</id>
    <title>BERT: Pre-training of Deep Bidirectional Transformers</title>
    <summary>We introduce a new language representation model called BERT.</summary>
    <published>2018-10-11T00:00:00Z</published>
    <author><name>Jacob Devlin</name></author>
    <link href="https://arxiv.org/pdf/1810.04805v2" rel="related" type="application/pdf" title="pdf"/>
  </entry>
</feed>
"""

EMPTY_ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    last_params: dict | None = None

    def __init__(self, response_text: str, *, raise_timeout: bool = False) -> None:
        self._response_text = response_text
        self._raise_timeout = raise_timeout

    def __call__(self, *args: object, **kwargs: object) -> "_FakeClient":
        return self

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, params: dict | None = None) -> _FakeResponse:
        _FakeClient.last_params = params
        if self._raise_timeout:
            import httpx

            raise httpx.TimeoutException("timed out")
        return _FakeResponse(self._response_text)


async def test_search_arxiv_topic_parses_all_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.papers.arxiv_client.httpx.AsyncClient", _FakeClient(MULTI_ENTRY_ATOM_XML)
    )

    results = await search_arxiv_topic("transformers", max_results=30)

    assert len(results) == 2
    assert results[0].arxiv_id == "1706.03762v5"
    assert results[0].title == "Attention Is All You Need"
    assert "Transformer" in results[0].abstract
    assert results[1].arxiv_id == "1810.04805v2"
    assert "BERT" in results[1].abstract


async def test_search_arxiv_topic_returns_empty_list_for_zero_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.papers.arxiv_client.httpx.AsyncClient", _FakeClient(EMPTY_ATOM_XML))

    results = await search_arxiv_topic("a very obscure topic with no papers")

    assert results == []


async def test_search_arxiv_topic_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.papers.arxiv_client.httpx.AsyncClient", _FakeClient(MULTI_ENTRY_ATOM_XML, raise_timeout=True)
    )

    with pytest.raises(ArxivUnavailableError):
        await search_arxiv_topic("transformers")


async def test_search_arxiv_topic_strips_quotes_from_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `"` in the topic string must never let user input escape the quoted
    arXiv phrase search (query-syntax injection)."""
    fake_client = _FakeClient(EMPTY_ATOM_XML)
    monkeypatch.setattr("app.papers.arxiv_client.httpx.AsyncClient", fake_client)

    await search_arxiv_topic('transformers" OR cat:cs.AI')

    search_query = _FakeClient.last_params["search_query"]
    # Only the two wrapping quotes from `all:"<topic>"` should remain -- any
    # quote embedded in the user-supplied topic itself must be stripped.
    assert search_query.count('"') == 2
    assert search_query == 'all:"transformers OR cat:cs.AI"'


def test_punctuation_only_author_entries_are_dropped() -> None:
    """arXiv's API returns GLM-5 (2602.15763) as "GLM-5-Team", ":", "Aohan
    Zeng", ... -- the ":" is a split artifact, not an author."""
    from app.papers.arxiv_client import _parse_first_entry

    atom = MULTI_ENTRY_ATOM_XML.replace(
        "<author><name>Ashish Vaswani</name></author>",
        "<author><name> GLM-5-Team</name></author><author><name> :</name></author>"
        "<author><name>Aohan Zeng</name></author>",
    )

    metadata = _parse_first_entry(atom)

    assert metadata is not None
    assert metadata.authors == ["GLM-5-Team", "Aohan Zeng"]
