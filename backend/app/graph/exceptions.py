"""Typed exceptions for the citation-graph domain (Phase 7 slice 2 --
docs/ARCHITECTURE.md's "Phase 7 slice 2 decisions" subsection).
"""

from app.core.errors import AppError


class OpenAlexUnavailableError(AppError):
    """The OpenAlex API timed out or returned an error -- distinct from "this
    paper genuinely has no OpenAlex record", which ``resolve_openalex_work``
    reports by returning ``None``, not by raising."""

    status_code = 502
    code = "openalex_unavailable"
