"""Client for OpenAlex's public Works API (api.openalex.org) -- resolves a
paper's OpenAlex citation record by DOI or title (docs/ARCHITECTURE.md's
"Phase 7 slice 2 decisions" subsection).

Mirrors ``app.papers.arxiv_client``/``app.coderesearch.github_client``'s
exact discipline: a fixed host allowlist, one ``httpx.AsyncClient`` per call
with a configurable timeout, ``response.raise_for_status()``, a typed
exception for timeout/HTTP failure. No bundled/default credential -- OpenAlex
works fully unauthenticated; an optional polite-pool ``mailto`` param (from
``Settings.openalex_contact_email``) only improves rate-limit treatment when
an operator sets it, never required.

"This paper has no OpenAlex record" is a normal, expected outcome (most
smaller/older/preprint-only papers simply aren't indexed) -- callers get
``None``, never an exception, for that case.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.graph.exceptions import OpenAlexUnavailableError

logger = get_logger(__name__)

# The only host any request in this module is ever sent to -- same
# "allowlist, not trust-then-catch" discipline as arxiv_client/github_client,
# even though (unlike those modules) no attacker-influenced URL is ever
# parsed here; the constant documents and pins the invariant regardless.
_ALLOWED_HOSTS = {"api.openalex.org"}
_API_BASE = "https://api.openalex.org"

_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:")


@dataclass(frozen=True)
class OpenAlexWork:
    openalex_id: str
    # OpenAlex work ids (e.g. "https://openalex.org/W123...") this work
    # cites -- the only other field this task needs out of the response.
    referenced_works: list[str]


def _normalize_doi(doi: str) -> str:
    """Strips a URL/scheme prefix so ``doi:`` OpenAlex lookups get the bare
    DOI OpenAlex's API expects, regardless of how ``Paper.doi`` was stored.
    """
    stripped = doi.strip()
    lowered = stripped.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            return stripped[len(prefix) :]
    return stripped


# Paper.doi is derived from untrusted PDF/arXiv metadata and is interpolated
# into a URL *path*, so it must not be able to smuggle "?", "#", "%" or "../"
# (httpx normalizes dot-segments, letting "10.1/../../x" retarget another
# endpoint on the allowlisted host and inject query params).
_DOI_PATTERN = re.compile(r"^10\.\d+/\S+$")


def _safe_doi_path(doi: str) -> str | None:
    """Returns the percent-encoded DOI, or ``None`` if it isn't a plausible
    DOI (caller then falls back to the title search instead)."""
    bare = _normalize_doi(doi)
    if not _DOI_PATTERN.match(bare) or any(segment in (".", "..") for segment in bare.split("/")):
        return None
    return quote(bare, safe="/")


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def _mailto_params() -> dict[str, str]:
    contact_email = get_settings().openalex_contact_email
    return {"mailto": contact_email} if contact_email else {}


def _parse_work(data: dict[str, object]) -> OpenAlexWork:
    openalex_id = str(data.get("id") or "")
    referenced_works = [str(work_id) for work_id in (data.get("referenced_works") or [])]
    return OpenAlexWork(openalex_id=openalex_id, referenced_works=referenced_works)


async def resolve_openalex_work(*, doi: str | None = None, title: str | None = None) -> OpenAlexWork | None:
    """Resolves by DOI (``GET /works/doi:{doi}``) if ``doi`` is given, else
    falls back to a title search (``GET /works?search={title}&per_page=5``),
    matching ``arxiv_client``'s by-title fallback pattern. Returns ``None``
    (not an error) for a genuine "not in OpenAlex" outcome; exactly one of
    ``doi``/``title`` is expected from the caller, and a call with neither
    also returns ``None``.
    """
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=settings.openalex_api_timeout_seconds) as client:
            safe_doi = _safe_doi_path(doi) if doi else None
            if safe_doi:
                response = await client.get(f"{_API_BASE}/works/doi:{safe_doi}", params=_mailto_params())
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return _parse_work(response.json())

            if title:
                response = await client.get(
                    f"{_API_BASE}/works", params={**_mailto_params(), "search": title, "per_page": "5"}
                )
                response.raise_for_status()
                # Top search hit is only trusted if its title actually matches:
                # a fuzzy wrong hit would become a confidence=1.0 "external
                # fact" edge to an unrelated work.
                wanted = _normalize_title(title)
                for result in response.json().get("results", []):
                    if _normalize_title(str(result.get("display_name") or result.get("title") or "")) == wanted:
                        return _parse_work(result)
                return None

            return None
    except httpx.TimeoutException as exc:
        raise OpenAlexUnavailableError("OpenAlex API request timed out") from exc
    except httpx.HTTPError as exc:
        raise OpenAlexUnavailableError("OpenAlex API request failed") from exc
