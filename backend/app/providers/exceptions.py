"""Typed exceptions for the providers domain — never a bare ``Exception``,
each maps to the API error envelope (API_SPEC.md Conventions)."""

from app.core.errors import AppError


class ProviderNotFoundError(AppError):
    status_code = 404
    code = "provider_not_found"


class ProviderValidationError(AppError):
    """Raised for a bad verify-connection request or a credential the
    provider rejected before any network round-trip was attempted (e.g. a
    non-loopback ``endpoint``, or the wrong credential field for this
    provider's ``auth`` type)."""

    status_code = 400
    code = "provider_validation_error"


class ProviderConnectionError(AppError):
    """Raised when the provider was reachable-in-principle but the actual
    verification call failed (bad key, unreachable endpoint, etc.)."""

    status_code = 502
    code = "provider_connection_error"
