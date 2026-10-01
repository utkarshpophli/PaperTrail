"""Typed exceptions for the auth domain. Never raise bare Exception here —
each maps to a specific API error envelope code (API_SPEC.md Conventions).
"""

from app.core.errors import AppError


class EmailAlreadyRegisteredError(AppError):
    status_code = 409
    code = "email_already_registered"


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"


class InvalidTokenError(AppError):
    status_code = 401
    code = "invalid_token"
