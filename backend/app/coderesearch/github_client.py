"""Client for GitHub's REST API (api.github.com) -- resolves repository
metadata, README text, and search results for the Code Research feature
(docs/ARCHITECTURE.md's Code Research (Phase 8) section).

Mirrors ``app.papers.arxiv_client``'s exact discipline: a fixed host
allowlist checked before any user-supplied URL is trusted, one
``httpx.AsyncClient`` per call with a configurable timeout,
``response.raise_for_status()``, typed exceptions for timeout/HTTP-error/
not-found. No bundled/default token -- GitHub's API works unauthenticated at
a low rate limit (fine for MVP); a token, when given, is per-request user
input sent only as an ``Authorization`` header, never logged, never
persisted server-side.
"""

import base64
import re
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from app.coderesearch.exceptions import (
    GithubFileNotTextError,
    GithubFileTooLargeError,
    GithubNotFoundError,
    GithubUnavailableError,
    InvalidRepositoryPathError,
    InvalidRepositoryUrlError,
)
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API_BASE = "https://api.github.com"

# The only hosts a user-submitted repository URL is ever trusted to name --
# same "allowlist before fetch, not trust-then-catch" discipline as
# arxiv_client._ALLOWED_PDF_HOSTS. github.com is the URL a user actually
# copy-pastes; api.github.com is where every real request in this module
# goes, listed for completeness even though no user input is ever parsed
# against it directly.
ALLOWED_HOSTS = frozenset({"github.com", "api.github.com"})

_REPO_PATH_RE = re.compile(r"^/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$")


class RepoMetadata(BaseModel):
    owner: str
    name: str
    description: str | None = None
    stars: int | None = None
    url: str


def parse_github_url(url: str) -> tuple[str, str]:
    """Validates ``url`` is a ``github.com/{owner}/{repo}`` URL and returns
    ``(owner, repo)`` -- raises ``InvalidRepositoryUrlError`` for anything
    else (wrong host, wrong scheme, missing/extra path segments) before any
    GitHub API call is ever attempted.
    """
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise InvalidRepositoryUrlError(f"Invalid repository URL: {url!r}") from exc

    if parsed.scheme != "https" or parsed.host != "github.com":
        raise InvalidRepositoryUrlError(
            f"Refusing repository URL {url!r} -- only https://github.com/{{owner}}/{{repo}} URLs are accepted"
        )

    match = _REPO_PATH_RE.match(parsed.path)
    if match is None:
        raise InvalidRepositoryUrlError(f"Could not parse an owner/repo pair out of {url!r}")
    return match.group(1), match.group(2)


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def fetch_repo_metadata(owner: str, repo: str, token: str | None) -> RepoMetadata:
    """``GET /repos/{owner}/{repo}``. ``token`` is optional and never
    required -- unauthenticated GitHub API calls work at a low rate limit,
    acceptable for MVP."""
    settings = get_settings()
    url = f"{_API_BASE}/repos/{owner}/{repo}"
    try:
        async with httpx.AsyncClient(timeout=settings.github_api_timeout_seconds) as client:
            response = await client.get(url, headers=_headers(token))
            if response.status_code == 404:
                raise GithubNotFoundError(f"GitHub repo {owner}/{repo} not found")
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise GithubUnavailableError("GitHub API request timed out") from exc
    except httpx.HTTPError as exc:
        raise GithubUnavailableError("GitHub API request failed") from exc

    data = response.json()
    return RepoMetadata(
        owner=(data.get("owner") or {}).get("login", owner),
        name=data.get("name", repo),
        description=data.get("description"),
        stars=data.get("stargazers_count"),
        url=data.get("html_url", f"https://github.com/{owner}/{repo}"),
    )


async def search_repos_by_query(query: str, token: str | None, max_results: int = 10) -> list[RepoMetadata]:
    """``GET /search/repositories?q=...`` -- used for official-implementation
    detection. Returns ``[]`` for zero matches rather than raising, same
    "empty result is a valid outcome" precedent as
    ``arxiv_client.search_arxiv_topic``."""
    settings = get_settings()
    url = f"{_API_BASE}/search/repositories"
    params = {"q": query, "per_page": str(max(1, min(max_results, 100)))}
    try:
        async with httpx.AsyncClient(timeout=settings.github_api_timeout_seconds) as client:
            response = await client.get(url, params=params, headers=_headers(token))
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise GithubUnavailableError("GitHub API search request timed out") from exc
    except httpx.HTTPError as exc:
        raise GithubUnavailableError("GitHub API search request failed") from exc

    items = response.json().get("items", [])
    return [
        RepoMetadata(
            owner=(item.get("owner") or {}).get("login", ""),
            name=item.get("name", ""),
            description=item.get("description"),
            stars=item.get("stargazers_count"),
            url=item.get("html_url", ""),
        )
        for item in items[:max_results]
    ]


async def fetch_readme(owner: str, repo: str, token: str | None) -> str:
    """``GET /repos/{owner}/{repo}/readme`` -- read-only, text only, never
    executed. Raises ``GithubNotFoundError`` if the repo has no README,
    ``GithubUnavailableError`` on timeout/HTTP failure; the caller
    (``app.evidence.implementation_plan``) treats either as "no README
    available" and degrades gracefully rather than failing plan generation.
    """
    settings = get_settings()
    url = f"{_API_BASE}/repos/{owner}/{repo}/readme"
    try:
        async with httpx.AsyncClient(timeout=settings.github_api_timeout_seconds) as client:
            response = await client.get(url, headers=_headers(token))
            if response.status_code == 404:
                raise GithubNotFoundError(f"GitHub repo {owner}/{repo} has no README")
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise GithubUnavailableError("GitHub API request timed out") from exc
    except httpx.HTTPError as exc:
        raise GithubUnavailableError("GitHub API request failed") from exc

    data = response.json()
    content = data.get("content", "")
    encoding = data.get("encoding", "base64")
    if encoding != "base64":
        return content
    try:
        return base64.b64decode(content).decode("utf-8", errors="replace")
    except (ValueError, TypeError) as exc:
        raise GithubUnavailableError("Failed to decode README content") from exc


# ---- repository tree + file content (Phase 8 slice 2: claim-to-code linking)

MAX_TREE_PATHS = 500
DEFAULT_MAX_FILE_BYTES = 30_000

# Fixed allowlist: only source-code-like files are worth offering to a model
# as candidate implementations of a claim -- data/weights/images/notebooks are
# noise (and a notebook's JSON wrapper would defeat verbatim-excerpt matching).
CODE_EXTENSIONS = frozenset(
    {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cc", ".cpp", ".cu", ".cuh", ".h", ".hpp",
        ".go", ".rs", ".jl", ".r", ".scala", ".kt", ".swift", ".lua", ".rb", ".cs",
    }
)  # fmt: skip
_VENDORED_DIRS = frozenset(
    {"node_modules", ".git", "dist", "build", "vendor", "third_party", "__pycache__", ".venv", "venv", "site-packages"}
)
_NAME_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
# Fits the code_links.file_path column (String(1024)); a longer path would otherwise fail at insert as an unhandled DB error.
MAX_PATH_CHARS = 500


class RepoTree(BaseModel):
    branch: str
    paths: list[str]
    # True if either GitHub itself truncated the tree or our own cap dropped
    # paths -- the caller must not treat ``paths`` as the whole repo.
    truncated: bool


def _check_name_segment(value: str, what: str) -> None:
    if not _NAME_SEGMENT_RE.fullmatch(value) or value in (".", ".."):
        raise InvalidRepositoryPathError(f"Invalid repository {what}")


def _safe_content_path(path: str) -> str:
    """Percent-encodes each ``/``-separated segment. Rejects anything that
    could retarget the request (httpx normalizes dot-segments in URL paths,
    same class of issue as ``app.graph.openalex_client._safe_doi_path``)."""
    if not path or len(path) > MAX_PATH_CHARS or path.startswith("/") or "\\" in path or _CONTROL_CHARS_RE.search(path):
        raise InvalidRepositoryPathError("Invalid repository file path")
    segments = path.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise InvalidRepositoryPathError("Invalid repository file path")
    return "/".join(quote(segment, safe="") for segment in segments)


async def _get_json_object(url: str, token: str | None, not_found_message: str) -> dict[str, object]:
    """One GET against the fixed GitHub API host. No redirects are followed
    (a 3xx fails ``raise_for_status``), and any non-JSON / non-object body
    maps to the typed unavailable error rather than surfacing as a 500."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=settings.github_api_timeout_seconds, follow_redirects=False) as client:
            response = await client.get(url, headers=_headers(token))
            if response.status_code == 404:
                raise GithubNotFoundError(not_found_message)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException as exc:
        raise GithubUnavailableError("GitHub API request timed out") from exc
    except httpx.HTTPError as exc:
        raise GithubUnavailableError("GitHub API request failed") from exc
    except ValueError as exc:
        raise GithubUnavailableError("GitHub API returned an invalid response") from exc
    if not isinstance(data, dict):
        raise GithubUnavailableError("GitHub API returned an unexpected response shape")
    return data


def _is_code_path(path: str) -> bool:
    if len(path) > MAX_PATH_CHARS or _CONTROL_CHARS_RE.search(path):
        return False
    segments = path.split("/")
    if any(segment in _VENDORED_DIRS for segment in segments[:-1]):
        return False
    name = segments[-1]
    return "." in name and "." + name.rsplit(".", 1)[1].lower() in CODE_EXTENSIONS


async def fetch_repo_tree(owner: str, repo: str, token: str | None) -> RepoTree:
    """Default branch via ``GET /repos/{o}/{r}``, then
    ``GET /repos/{o}/{r}/git/trees/{branch}?recursive=1``. Only blob entries
    with a code extension outside vendored directories are kept, capped at
    ``MAX_TREE_PATHS``."""
    _check_name_segment(owner, "owner")
    _check_name_segment(repo, "name")
    repo_data = await _get_json_object(
        f"{_API_BASE}/repos/{owner}/{repo}", token, f"GitHub repo {owner}/{repo} not found"
    )
    branch = repo_data.get("default_branch")
    if not isinstance(branch, str) or not branch or _CONTROL_CHARS_RE.search(branch):
        raise GithubUnavailableError("GitHub repo metadata has no usable default branch")

    tree_data = await _get_json_object(
        f"{_API_BASE}/repos/{owner}/{repo}/git/trees/{quote(branch, safe='')}?recursive=1",
        token,
        f"GitHub tree for {owner}/{repo}@{branch} not found",
    )
    entries = tree_data.get("tree")
    if not isinstance(entries, list):
        raise GithubUnavailableError("GitHub tree response has no entry list")

    paths = [
        entry["path"]
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("type") == "blob"
        and isinstance(entry.get("path"), str)
        and _is_code_path(entry["path"])
    ]
    truncated = bool(tree_data.get("truncated")) or len(paths) > MAX_TREE_PATHS
    return RepoTree(branch=branch, paths=paths[:MAX_TREE_PATHS], truncated=truncated)


async def fetch_file_content(
    owner: str, repo: str, path: str, token: str | None, max_bytes: int = DEFAULT_MAX_FILE_BYTES
) -> str:
    """``GET /repos/{o}/{r}/contents/{path}`` -- text only, never executed.
    The size cap is enforced against GitHub's reported ``size`` *before* any
    base64 decoding."""
    _check_name_segment(owner, "owner")
    _check_name_segment(repo, "name")
    safe_path = _safe_content_path(path)
    data = await _get_json_object(
        f"{_API_BASE}/repos/{owner}/{repo}/contents/{safe_path}", token, f"GitHub file {path!r} not found"
    )
    if data.get("type") != "file":
        raise GithubNotFoundError(f"GitHub path {path!r} is not a regular file")
    size = data.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise GithubUnavailableError("GitHub file response has no usable size")
    if size > max_bytes:
        raise GithubFileTooLargeError(f"File {path!r} is {size} bytes, over the {max_bytes}-byte limit")
    content = data.get("content")
    if data.get("encoding") != "base64" or not isinstance(content, str):
        raise GithubUnavailableError("GitHub file response has unexpected encoding")
    try:
        raw = base64.b64decode(content)
    except ValueError as exc:
        raise GithubUnavailableError("Failed to decode file content") from exc
    # The reported ``size`` is only a hint: bound what was actually delivered.
    if len(raw) > max_bytes:
        raise GithubFileTooLargeError(f"File {path!r} body is over the {max_bytes}-byte limit")
    if b"\x00" in raw:
        raise GithubFileNotTextError(f"File {path!r} is not a text file")
    return raw.decode("utf-8", errors="replace")
