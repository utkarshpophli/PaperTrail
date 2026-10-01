"""Client for arXiv's public Atom API (export.arxiv.org) — resolves paper
metadata by arXiv ID or title, and downloads the PDF.

The query call targets a fixed host directly. The PDF download URL, though,
comes from parsing that response — so it's validated against a host
allowlist before ever being fetched (see download_pdf), the same way any
server-side-constructed outbound URL should be. Failures surface as typed
errors, never a bare exception reaching the route.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import httpx
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.logging import get_logger
from app.papers.exceptions import ArxivNotFoundError, ArxivUnavailableError, InvalidFileTypeError

logger = get_logger(__name__)

_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5}(v\d+)?)")
_PDF_MAGIC = b"%PDF-"
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
_WHITESPACE_RE = re.compile(r"\s+")

# Phase 5 (Discovery): `topic` in search_arxiv_topic is user-controlled free
# text interpolated into `search_query=all:"<topic>"` -- a bare `"` would let
# it escape the quoted phrase and inject arXiv query-syntax (e.g. a stray
# `" OR cat:cs.AI`). Strip characters that have syntactic meaning in arXiv's
# query grammar rather than trying to support/parse a query DSL from user
# input (same "treat as untrusted string, not a search-DSL query" call as any
# other user-input-into-external-API path in this codebase).
_UNSAFE_QUERY_CHARS_RE = re.compile(r'["\\]')

# The Atom response's <link href> is attacker-controllable if the arXiv API
# call (or any intermediary) is ever tampered with — on-path HTTP tampering,
# a compromised proxy, or a future bug in _parse_first_entry. Without this
# allowlist, download_pdf would fetch and persist whatever URL that field
# contains, from inside server infrastructure (SSRF). Only arXiv's own hosts
# are ever legitimate here.
_ALLOWED_PDF_HOSTS = {"arxiv.org", "export.arxiv.org"}


@dataclass(frozen=True)
class ArxivMetadata:
    arxiv_id: str
    title: str
    authors: list[str]
    year: int | None
    pdf_url: str
    # Populated from the Atom <summary> element -- "" for the (rare) entry
    # that has none, never None, so downstream code (Phase 5 discovery) can
    # treat it as plain text unconditionally.
    abstract: str = ""


async def resolve_arxiv_metadata(*, arxiv_id: str | None = None, title: str | None = None) -> ArxivMetadata:
    """Resolves metadata + a PDF URL for a paper by arXiv ID or title.
    Exactly one of ``arxiv_id``/``title`` must be given (enforced by the
    caller's request schema, not re-validated here).
    """
    params = {"id_list": arxiv_id, "max_results": "1"} if arxiv_id else {"search_query": f'ti:"{title}"', "max_results": "1"}
    settings = get_settings()

    try:
        async with httpx.AsyncClient(timeout=settings.arxiv_api_timeout_seconds) as client:
            response = await client.get(_ARXIV_API_URL, params=params)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ArxivUnavailableError("arXiv API request timed out") from exc
    except httpx.HTTPError as exc:
        raise ArxivUnavailableError("arXiv API request failed") from exc

    metadata = _parse_first_entry(response.text)
    if metadata is None:
        raise ArxivNotFoundError("No arXiv paper found for the given identifier or title")
    return metadata


async def search_arxiv_topic(topic: str, max_results: int = 30) -> list[ArxivMetadata]:
    """A genuine multi-result arXiv topic search (Phase 5 Discovery), distinct
    from ``resolve_arxiv_metadata``'s by-id/by-title single-result resolve
    used by ``/papers/from-arxiv`` -- relevance-sorted, all-fields query,
    parses every ``<entry>`` in the response.

    Returns ``[]`` for zero matches rather than raising -- an empty topic
    search result is a valid, non-error outcome (unlike "paper not found by
    exact id/title", which is what ``ArxivNotFoundError`` means for the other
    resolver). Raises ``ArxivUnavailableError`` on timeout/HTTP failure, same
    as ``resolve_arxiv_metadata``.
    """
    safe_topic = _UNSAFE_QUERY_CHARS_RE.sub("", topic).strip()
    params = {
        "search_query": f'all:"{safe_topic}"',
        "sortBy": "relevance",
        "sortOrder": "descending",
        "max_results": str(max_results),
    }
    settings = get_settings()

    try:
        async with httpx.AsyncClient(timeout=settings.arxiv_api_timeout_seconds) as client:
            response = await client.get(_ARXIV_API_URL, params=params)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ArxivUnavailableError("arXiv API request timed out") from exc
    except httpx.HTTPError as exc:
        raise ArxivUnavailableError("arXiv API request failed") from exc

    return _parse_entries(response.text)


async def download_pdf(pdf_url: str, dest_path: str) -> None:
    """Downloads the PDF at ``pdf_url`` to ``dest_path`` on disk.

    ``pdf_url`` came from a parsed Atom response, not a request the caller
    directly controls, but it is still validated as if it were untrusted
    (host allowlist, no redirects, magic-byte + size cap on the body) — the
    same discipline as the direct-upload path, since the failure mode of
    skipping it is a server-side SSRF/fetch of arbitrary content.
    """
    parsed = httpx.URL(pdf_url)
    if parsed.scheme != "https" or parsed.host not in _ALLOWED_PDF_HOSTS:
        raise ArxivUnavailableError("Refusing to download from an unexpected host")

    settings = get_settings()
    max_bytes = settings.max_upload_size_bytes
    try:
        async with httpx.AsyncClient(timeout=settings.arxiv_api_timeout_seconds, follow_redirects=False) as client:
            async with client.stream("GET", pdf_url) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                first_chunk = True
                async for chunk in response.aiter_bytes(_DOWNLOAD_CHUNK_SIZE):
                    if first_chunk:
                        if not chunk.startswith(_PDF_MAGIC):
                            raise InvalidFileTypeError("arXiv did not return a PDF")
                        first_chunk = False
                    total += len(chunk)
                    if total > max_bytes:
                        raise ArxivUnavailableError(f"PDF exceeds the {max_bytes} byte limit")
                    chunks.append(chunk)
    except httpx.TimeoutException as exc:
        raise ArxivUnavailableError("Timed out downloading PDF from arXiv") from exc
    except httpx.HTTPError as exc:
        raise ArxivUnavailableError("Failed to download PDF from arXiv") from exc

    await run_in_threadpool(Path(dest_path).write_bytes, b"".join(chunks))


def _parse_entry(entry: ET.Element) -> ArxivMetadata:
    entry_id = entry.findtext(f"{_ATOM_NS}id", default="") or ""
    match = _ARXIV_ID_RE.search(entry_id)
    resolved_id = match.group(1) if match else entry_id.rsplit("/", 1)[-1]

    title = (entry.findtext(f"{_ATOM_NS}title", default="") or "").strip().replace("\n", " ")
    abstract = _WHITESPACE_RE.sub(" ", entry.findtext(f"{_ATOM_NS}summary", default="") or "").strip()
    # arXiv splits "GLM-5-Team: Aohan Zeng, ..." into a separate ":" author;
    # an entry with no letter or digit is that kind of artifact, not a name.
    names = ((name.text or "").strip() for name in entry.findall(f"{_ATOM_NS}author/{_ATOM_NS}name"))
    authors = [name for name in names if any(ch.isalnum() for ch in name)]
    published = entry.findtext(f"{_ATOM_NS}published", default="") or ""
    year = int(published[:4]) if published[:4].isdigit() else None

    pdf_url = ""
    for link in entry.findall(f"{_ATOM_NS}link"):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = link.get("href", "")
            break
    if not pdf_url and resolved_id:
        pdf_url = f"https://arxiv.org/pdf/{resolved_id}"

    return ArxivMetadata(
        arxiv_id=resolved_id, title=title, authors=authors, year=year, pdf_url=pdf_url, abstract=abstract
    )


def _parse_first_entry(atom_xml: str) -> ArxivMetadata | None:
    root = ET.fromstring(atom_xml)  # trusted, fixed-host response — not user-supplied XML
    entry = root.find(f"{_ATOM_NS}entry")
    if entry is None:
        return None
    return _parse_entry(entry)


def _parse_entries(atom_xml: str) -> list[ArxivMetadata]:
    root = ET.fromstring(atom_xml)  # trusted, fixed-host response — not user-supplied XML
    return [_parse_entry(entry) for entry in root.findall(f"{_ATOM_NS}entry")]
