"""Shared typed-error base and API error envelope, per API_SPEC.md Conventions:
``{ "error": { "code": str, "message": str, "detail"?: object } }``.

Domain modules (auth, papers, evidence, ...) subclass ``AppError`` instead of
raising bare ``Exception`` — the app-wide handler in ``app.main`` converts any
``AppError`` into the envelope automatically.
"""

from typing import Any


class AppError(Exception):
    """Base class for typed application errors mapped to the API error envelope."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)
