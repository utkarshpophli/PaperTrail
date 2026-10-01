"""Typed exceptions for the papers domain — never a bare ``Exception``, each
maps to the API error envelope (API_SPEC.md Conventions)."""

from app.core.errors import AppError


class PaperNotFoundError(AppError):
    status_code = 404
    code = "paper_not_found"


class PageNotFoundError(AppError):
    status_code = 404
    code = "page_not_found"


class FigureNotFoundError(AppError):
    status_code = 404
    code = "figure_not_found"


class PaperNotParsedError(AppError):
    status_code = 409
    code = "paper_not_parsed"


class SourcePdfMissingError(AppError):
    status_code = 409
    code = "source_pdf_missing"


class InvalidFileTypeError(AppError):
    status_code = 422
    code = "invalid_file_type"


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class ArxivNotFoundError(AppError):
    status_code = 404
    code = "arxiv_not_found"


class ArxivUnavailableError(AppError):
    status_code = 502
    code = "arxiv_unavailable"
