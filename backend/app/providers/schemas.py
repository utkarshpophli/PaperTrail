"""Request/response models for the providers routes."""

from pydantic import BaseModel, Field

from app.providers.base import ModelKind


class VerifyConnectionRequest(BaseModel):
    """Exactly one of ``api_key``/``endpoint`` is expected, depending on the
    target provider's ``auth`` catalog field — enforced in the route handler
    since the correct field depends on which provider id is in the URL, not
    on this body alone."""

    api_key: str | None = None
    endpoint: str | None = None


class ModelListItem(BaseModel):
    id: str
    label: str
    context_length: int | None = None
    kind: ModelKind = "chat"


class ModelListResponse(BaseModel):
    """Models of the requested ``kind`` only (``list_models``'s ``kind``
    query param, default ``"chat"``), sorted by label. A live-listing
    failure is a real error (see providers/router.py::list_models), never
    silently swapped for a static/known-model list."""

    models: list[ModelListItem]


class ModelPingRequest(VerifyConnectionRequest):
    model: str = Field(min_length=1, max_length=200)


class ModelPingResponse(BaseModel):
    ok: bool
    latency_ms: int
