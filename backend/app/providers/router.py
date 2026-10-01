"""Providers routes: catalog listing, live model listing, and a single-model
connectivity ping.

Router lives in this domain package rather than a shared ``routers/`` dir —
same module-owns-its-router pattern as ``app.papers.router``.

``GET /providers`` requires authentication even though the catalog itself is
static, non-sensitive metadata: API_SPEC.md's Conventions state a bearer
token "on every authenticated route" without carving out an exception for
this one, and SECURITY.md's general posture favors consistency over
convenience when in doubt.
"""

import time

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.rate_limit import limiter, rate_limit_key
from app.models.user import User
from app.providers import registry
from app.providers.base import AIProvider, ModelKind
from app.providers.exceptions import ProviderConnectionError, ProviderNotFoundError, ProviderValidationError
from app.providers.model_kinds import classify_model_id
from app.providers.ping import ping_chat, ping_embed
from app.providers.redaction import redacting
from app.providers.registry import ProviderCatalogEntry
from app.providers.schemas import (
    ModelListItem,
    ModelListResponse,
    ModelPingRequest,
    ModelPingResponse,
    VerifyConnectionRequest,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/providers", tags=["providers"])


def _get_catalog_entry(provider_id: str) -> ProviderCatalogEntry:
    for entry in registry.list_provider_catalog():
        if entry.id == provider_id:
            return entry
    raise ProviderNotFoundError(f"Unknown provider '{provider_id}'")


def _validate_credential_shape(entry: ProviderCatalogEntry, body: VerifyConnectionRequest) -> None:
    if entry.auth == "api_key":
        if not body.api_key:
            raise ProviderValidationError("This provider requires an api_key")
        if body.endpoint:
            raise ProviderValidationError("This provider does not accept an endpoint")
    else:  # auth == "none" (local/endpoint-based provider)
        if not body.endpoint:
            raise ProviderValidationError("This provider requires an endpoint")
        if body.api_key:
            raise ProviderValidationError("This provider does not accept an api_key")


def _build_provider(provider_id: str, body: VerifyConnectionRequest) -> AIProvider:
    """Shared by every route taking a per-request credential. The provider is
    wrapped so a credential echoed in an upstream error is scrubbed before it
    can reach a log line or a response."""
    try:
        provider = registry.build_provider(provider_id, api_key=body.api_key, endpoint=body.endpoint)
    except AppError:
        # Already typed and correctly coded (e.g. InvalidConfigError for a
        # non-loopback endpoint) - propagate as-is.
        raise
    except Exception as exc:
        # ponytail: broad catch is deliberate - build_provider is an external
        # module boundary whose non-AppError failure modes aren't fixed by
        # the contract. Never log the submitted api_key/endpoint here.
        logger.warning("provider_build_rejected provider_id=%s error_type=%s", provider_id, type(exc).__name__)
        raise ProviderValidationError(str(exc) or "Unable to construct this provider") from exc
    return redacting(provider, body.api_key)


@router.get("", response_model=list[ProviderCatalogEntry])
async def get_providers(current_user: User = Depends(get_current_user)) -> list[ProviderCatalogEntry]:
    return registry.list_provider_catalog()


@router.post("/{provider_id}/models", response_model=ModelListResponse)
@limiter.limit("10/minute", key_func=rate_limit_key)
async def list_models(
    request: Request,
    provider_id: str,
    body: VerifyConnectionRequest,
    kind: ModelKind = "chat",
    current_user: User = Depends(get_current_user),
) -> ModelListResponse:
    entry = _get_catalog_entry(provider_id)
    _validate_credential_shape(entry, body)
    provider = _build_provider(provider_id, body)

    try:
        models = await provider.list_models()
    except AppError:
        # Already typed (e.g. AuthenticationError, NotSupportedError) —
        # propagate as-is rather than masking it behind a static list.
        raise
    except Exception as exc:
        logger.warning("provider_list_models_failed provider_id=%s error_type=%s", provider_id, type(exc).__name__)
        raise ProviderConnectionError(str(exc) or "Unable to list models") from exc

    matching = sorted((m for m in models if m.kind == kind), key=lambda m: m.label.lower())
    return ModelListResponse(
        models=[
            ModelListItem(id=m.id, label=m.label, context_length=m.context_length, kind=m.kind) for m in matching
        ],
    )


@router.post("/{provider_id}/test-model", response_model=ModelPingResponse)
@limiter.limit("10/minute", key_func=rate_limit_key)
async def test_model(
    request: Request,
    provider_id: str,
    body: ModelPingRequest,
    current_user: User = Depends(get_current_user),
) -> ModelPingResponse:
    entry = _get_catalog_entry(provider_id)
    _validate_credential_shape(entry, body)
    provider = _build_provider(provider_id, body)

    started = time.perf_counter()
    try:
        if classify_model_id(body.model) == "embedding":
            await ping_embed(provider, body.model)
        else:
            await ping_chat(provider, body.model)
    except AppError:
        raise
    except Exception as exc:
        logger.warning("provider_test_model_failed provider_id=%s error_type=%s", provider_id, type(exc).__name__)
        raise ProviderConnectionError(str(exc) or "Unable to test this model") from exc

    logger.info("provider_model_tested provider_id=%s", provider_id)
    return ModelPingResponse(ok=True, latency_ms=round((time.perf_counter() - started) * 1000))
