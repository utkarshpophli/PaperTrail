"""Typed exceptions for the document pipeline. Per-page failures never raise
(they become an empty-text page, see parser.py) — this is only for failures
that make the whole file unreadable.
"""

from app.core.errors import AppError


class DocumentUnreadableError(AppError):
    """Raised when the PDF itself can't be opened at all (corrupt file,
    not a PDF, zero pages) — distinct from a single bad page, which is
    recorded in ``metadata['unparsed_pages']`` instead of raising.
    """

    status_code = 422
    code = "document_unreadable"
