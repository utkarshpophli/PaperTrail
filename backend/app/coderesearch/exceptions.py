"""Typed exceptions for the code-research domain -- never a bare
``Exception``, each maps to the API error envelope (API_SPEC.md
Conventions)."""

from app.core.errors import AppError


class InvalidRepositoryUrlError(AppError):
    """A user-submitted repository URL isn't a ``github.com/{owner}/{repo}``
    URL -- rejected before any GitHub API call is ever made, same
    validate-before-fetch discipline as ``app.papers.arxiv_client``'s host
    allowlist."""

    status_code = 422
    code = "invalid_repository_url"


class GithubNotFoundError(AppError):
    """The requested repository (or its README) doesn't exist on GitHub."""

    status_code = 404
    code = "github_repo_not_found"


class GithubUnavailableError(AppError):
    """The GitHub API timed out or returned an error -- distinct from "the
    repo doesn't exist"."""

    status_code = 502
    code = "github_unavailable"


class RepositoryNotFoundError(AppError):
    """No linked ``Repository`` row with the given id exists for this paper,
    or it belongs to a different paper/user -- both cases look identical to
    the caller, same row-level authorization discipline as
    ``app.papers.service.get_owned_paper``."""

    status_code = 404
    code = "repository_not_found"


class InvalidRepositoryPathError(AppError):
    """A repository file path (or owner/repo/branch segment) failed
    validation before being interpolated into a GitHub API URL -- absolute
    paths, ``..``/``.`` segments, backslashes and control characters are all
    rejected, never sanitized into something that might still traverse."""

    status_code = 422
    code = "invalid_repository_path"


class GithubFileTooLargeError(AppError):
    """The file exceeds the read-size cap -- rejected using GitHub's reported
    size before any content is decoded."""

    status_code = 422
    code = "github_file_too_large"


class GithubFileNotTextError(AppError):
    """The file body contains NUL bytes -- binary content masquerading as
    source, which is neither useful to a model nor storable in a text
    column."""

    status_code = 422
    code = "github_file_not_text"


class ClaimNotLinkableError(AppError):
    """Only ``method`` and ``reported-result`` claims describe something a
    code file can implement (docs/ARCHITECTURE.md, Phase 8 slice 2)."""

    status_code = 422
    code = "claim_not_linkable_to_code"


class CodeLinkNotFoundError(AppError):
    status_code = 404
    code = "code_link_not_found"
