"""Typed errors raised by provider adapters (``AIProvider`` implementations).

These are distinct from ``app.providers.exceptions`` (the providers *route*
domain's errors — ``ProviderNotFoundError``/``ProviderValidationError``/
``ProviderConnectionError``, owned by the Providers API). This module is the
adapter-level vocabulary: what a `generate`/`stream`/`embed`/`vision`/
`available_models` call itself can fail with, regardless of which route (or
future Evidence Engine caller) invokes it. The providers router currently
catches broad exceptions at its boundary and re-wraps them, but any other
caller depends on these specific types.

Every message must say what actually went wrong (auth vs. rate limit vs.
model-not-found vs. unreachable) — a generic "provider error" fails
docs/ARCHITECTURE.md's error-handling requirement.
"""

from app.core.errors import AppError


class NotSupportedError(AppError):
    """Raised when a provider/model genuinely lacks a capability
    (``embed``/``vision``) — never a silent no-op or empty-result instead."""

    status_code = 422
    code = "provider_capability_not_supported"


class ProviderUnavailableError(AppError):
    """The provider was unreachable, timed out, or returned a server-side
    (5xx-equivalent) failure."""

    status_code = 502
    code = "provider_unavailable"


class AuthenticationError(AppError):
    """The provider rejected the supplied credential (bad/expired API key)."""

    status_code = 401
    code = "provider_authentication_failed"


class StructuredOutputError(AppError):
    """The model's output failed schema validation twice (the one-retry
    budget in AI_PROVIDERS.md's hallucination handling) — surfaced to the
    caller rather than looping or accepting invalid output."""

    status_code = 502
    code = "structured_output_invalid"


class OutputTruncatedError(StructuredOutputError):
    """The model hit its output-token limit (``finish_reason: "length"``)
    before finishing its answer -- e.g. a reasoning model that spent the whole
    budget on chain-of-thought. Distinct from a schema failure: a repair
    retry cannot fix it, so it is raised directly instead of going through
    the structured-output retry."""

    code = "model_output_truncated"


class InvalidConfigError(AppError):
    """A provider was asked to construct/operate with a configuration that's
    invalid before any network round-trip — e.g. a non-loopback local
    endpoint (SECURITY.md's SSRF control) or a missing required credential.
    Raised immediately at construction/validation time, not on first use.
    """

    status_code = 422
    code = "provider_invalid_config"


class ModelNotFoundError(ProviderUnavailableError):
    """The provider reachable and credentialed, but does not know the
    requested model id. Subclasses ``ProviderUnavailableError`` so existing
    catch sites keep working; the 404 status/code let callers tell a typo from
    an outage."""

    status_code = 404
    code = "provider_model_not_found"
