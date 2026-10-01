"""Library-wide literature graph routes (Phase 7): ``GET /graph`` and
``GET /graph/papers/{id}/neighbors``, computed live (merged with persisted
citation edges) per request -- see ``app.graph.service``'s module docstring.
Also ``POST /graph/papers/{id}/citations/refresh`` (Phase 7 slice 2), the one
explicit action that fetches/persists ``CitationEdge`` rows.

The two ``GET`` routes' provider selection follows the exact same
per-request pattern as ``GET /discover/recommendations``: ``provider_id``/
``model``/``endpoint`` as query params, ``api_key`` via the
``X-Provider-Api-Key`` header (never a query param -- a secret in the URL is
trivially captured by access/proxy logs and browser history, per
SECURITY.md/CLAUDE.md's "API keys ... never logged" rule). The ``POST``
refresh route instead takes a flat provider-selection body (matching
``app.evidence.router.AssistantRequest``'s shape) since it's a state-changing
action, not a cacheable ``GET``.
"""

import uuid

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.logging import get_logger
from app.core.rate_limit import limiter, rate_limit_key
from app.db.session import get_db
from app.graph import citations as citations_service
from app.graph import service as graph_service
from app.graph.schemas import CitationEdgeResponse, LibraryGraphResponse
from app.models.citation_edge import CitationEdge
from app.models.user import User
from app.papers.service import get_owned_paper
from app.providers.base import AIProvider
from app.providers.errors import InvalidConfigError
from app.providers.redaction import redacting
from app.providers.registry import build_provider

logger = get_logger(__name__)
router = APIRouter(prefix="/graph", tags=["graph"])


class CitationRefreshRequest(BaseModel):
    """Body for ``POST /graph/papers/{id}/citations/refresh`` -- same flat
    per-request provider-selection shape as every other provider-calling
    route in this codebase (e.g. ``app.evidence.router.AssistantRequest``),
    router-local since nothing in ``app.graph.citations`` needs this exact
    shape.
    """

    provider_id: str
    api_key: str | None = None
    endpoint: str | None = None
    model: str = Field(min_length=1, max_length=200)


def _build_provider_or_raise(provider_id: str, api_key: str | None, endpoint: str | None) -> AIProvider:
    try:
        return redacting(build_provider(provider_id, api_key=api_key, endpoint=endpoint), api_key)
    except NotImplementedError as exc:
        # build_provider raises bare NotImplementedError (not an AppError)
        # for a catalogued-but-not-yet-adapted provider id -- translate it,
        # same fix as app.discovery.router.get_recommendations.
        raise InvalidConfigError(str(exc)) from exc


@router.get("", response_model=LibraryGraphResponse)
# 20/hour matches /discover/recommendations' ceiling -- both call out to a
# provider's embed() on every request without being a multi-stage pipeline
# (SECURITY.md: per-user limits on expensive endpoints).
@limiter.limit("20/hour", key_func=rate_limit_key)
async def get_library_graph(
    request: Request,
    provider_id: str,
    embed_model: str,
    endpoint: str | None = None,
    x_provider_api_key: str | None = Header(default=None, alias="X-Provider-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryGraphResponse:
    provider = _build_provider_or_raise(provider_id, x_provider_api_key, endpoint)
    return await graph_service.build_library_graph(db, provider, current_user.id, embed_model=embed_model)


@router.get("/papers/{paper_id}/neighbors", response_model=LibraryGraphResponse)
@limiter.limit("20/hour", key_func=rate_limit_key)
async def get_paper_neighbors(
    request: Request,
    paper_id: uuid.UUID,
    provider_id: str,
    embed_model: str,
    endpoint: str | None = None,
    x_provider_api_key: str | None = Header(default=None, alias="X-Provider-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryGraphResponse:
    provider = _build_provider_or_raise(provider_id, x_provider_api_key, endpoint)
    return await graph_service.build_paper_neighbors_graph(
        db, provider, current_user.id, paper_id, embed_model=embed_model
    )


@router.post("/papers/{paper_id}/citations/refresh", response_model=list[CitationEdgeResponse])
# 5/hour matches /discover/roadmap's ceiling -- a real external API call
# (OpenAlex) plus one provider.generate() call per confirmed edge, a
# comparably bounded-but-real-cost multi-stage operation (SECURITY.md:
# per-user limits on expensive endpoints).
@limiter.limit("5/hour", key_func=rate_limit_key)
async def refresh_paper_citations(
    request: Request,
    paper_id: uuid.UUID,
    body: CitationRefreshRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CitationEdge]:
    """Fetches real citation edges from OpenAlex, then runs the relation
    classifier over whatever was found. Never logs ``body.api_key`` -- same
    credential-handling discipline as ``app.evidence.router.analyze_paper``.
    """
    await get_owned_paper(db, paper_id, current_user.id)
    provider = _build_provider_or_raise(body.provider_id, body.api_key, body.endpoint)

    edges = await citations_service.fetch_citation_edges_for_paper(db, provider, current_user.id, paper_id)
    if not edges:
        return edges

    paper_ids = {edge.from_paper_id for edge in edges} | {edge.to_paper_id for edge in edges}
    papers_by_id = await citations_service.load_papers_for_classification(db, current_user.id, paper_ids)
    classified = await citations_service.classify_citation_relations(provider, edges, papers_by_id, body.model)
    await db.commit()

    logger.info(
        "citation_refresh_completed paper_id=%s user_id=%s edges=%s", paper_id, current_user.id, len(classified)
    )
    return classified
