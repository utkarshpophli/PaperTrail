"""Typed exceptions for the collections domain -- never a bare ``Exception``,
each maps to the API error envelope (API_SPEC.md Conventions)."""

from app.core.errors import AppError


class CollectionNotFoundError(AppError):
    """Raised when no collection with the given id exists, or it exists but
    belongs to a different user -- both cases look identical to the caller,
    same 404-not-403 row-level authorization discipline as
    ``app.papers.service.get_owned_paper``/``app.discovery.service.get_owned_landscape``."""

    status_code = 404
    code = "collection_not_found"
