"""Discovery routes: topic-landscape search (SSE), landscape retrieval +
Neural Map graph, user profile, and personalized recommendations (Phase 5);
research roadmap generation (SSE), retrieval/listing, and milestone-status
updates (Phase 6).

Router lives in this domain package, same module-owns-its-router pattern as
``app.evidence.router``/``app.papers.router`` -- this module only enforces
auth/ownership/rate-limits and adapts ``app.discovery.service``'s output to
SSE / the shared error envelope / response models.
"""

import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.logging import get_logger
from app.core.rate_limit import limiter, rate_limit_key
from app.db.session import get_db
from app.discovery import service as discovery_service
from app.discovery.schemas import (
    LandscapeGraphResponse,
    LandscapePromoteRequest,
    LandscapePromoteResponse,
    LandscapeSearchRequest,
    MilestoneUpdateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    RecommendationItem,
    RoadmapCreateRequest,
    RoadmapPaperTarget,
    RoadmapResponse,
    RoadmapSummary,
    TopicLandscapeResponse,
)
from app.models.profile import Profile
from app.models.roadmap import Roadmap
from app.models.topic_landscape import TopicLandscape
from app.models.user import User
from app.papers.service import get_owned_paper
from app.providers.errors import InvalidConfigError

logger = get_logger(__name__)
router = APIRouter(prefix="/discover", tags=["discovery"])


def _format_sse_event(event: "discovery_service.AnalysisEvent") -> bytes:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n".encode("utf-8")


@router.post("/landscape")
# 5/hour matches /papers/{id}/analyze's ceiling -- both are multi-stage
# pipelines with several provider round-trips per call (SECURITY.md:
# per-user limits on expensive endpoints).
@limiter.limit("5/hour", key_func=rate_limit_key)
async def create_landscape(
    request: Request,
    body: LandscapeSearchRequest,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Streams ``AnalysisEvent``s as SSE, same format/pre-flight-peek pattern
    as ``app.evidence.router.analyze_paper``.

    Never logs any ``api_key`` -- same credential-handling discipline as the
    Evidence Engine's routes.
    """
    logger.info("landscape_search_started user_id=%s topic=%s", current_user.id, body.topic)

    events = discovery_service.run_landscape_search(
        user_id=current_user.id,
        topic=body.topic,
        provider_id=body.provider_id,
        api_key=body.api_key,
        endpoint=body.endpoint,
        model=body.model,
        embed_model=body.embed_model,
    )

    # Peek the first event outside the streamed body: StreamingResponse
    # commits status 200 + headers before pulling its first chunk, so a
    # pre-flight failure raised on the generator's first step must be
    # awaited here to surface as a normal typed-error JSON response instead
    # of an SSE stream that already claimed success (same fix as
    # app.evidence.router's analyze_paper/assistant_paper).
    try:
        first_event: discovery_service.AnalysisEvent | None = await events.__anext__()
    except StopAsyncIteration:
        first_event = None

    async def _stream() -> AsyncIterator[bytes]:
        if first_event is not None:
            yield _format_sse_event(first_event)
        async for event in events:
            yield _format_sse_event(event)

    return StreamingResponse(_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/landscape/{landscape_id}", response_model=TopicLandscapeResponse)
async def get_landscape(
    landscape_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TopicLandscape:
    return await discovery_service.get_owned_landscape(db, landscape_id, current_user.id)


@router.get("/landscape/{landscape_id}/graph", response_model=LandscapeGraphResponse)
async def get_landscape_graph(
    landscape_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LandscapeGraphResponse:
    landscape = await discovery_service.get_owned_landscape(db, landscape_id, current_user.id)
    return discovery_service.build_landscape_graph(landscape)


@router.post("/landscape/{landscape_id}/promote", response_model=LandscapePromoteResponse)
# 10/minute matches /collections's write-route precedent (security review:
# every other mutating endpoint in this slice has a limiter, this one didn't).
@limiter.limit("10/minute", key_func=rate_limit_key)
async def promote_landscape(
    request: Request,
    landscape_id: uuid.UUID,
    body: LandscapePromoteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LandscapePromoteResponse:
    """Copies this landscape's already-ingested, owned papers into a new or
    existing Collection -- the route Phase 5 deferred until Collections
    existed (ARCHITECTURE.md's Phase 7 decisions)."""
    collection, added, skipped = await discovery_service.promote_landscape(
        db, current_user.id, landscape_id, body.collection_id, body.collection_name
    )
    return LandscapePromoteResponse(collection_id=collection.id, added=added, skipped_not_ingested=skipped)


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Profile:
    return await discovery_service.get_or_create_profile(db, current_user.id)


@router.put("/profile", response_model=ProfileResponse)
async def put_profile(
    body: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Profile:
    return await discovery_service.update_profile(
        db, current_user.id, interests=body.interests, level=body.level, goals=body.goals
    )


@router.get("/recommendations", response_model=list[RecommendationItem])
# 20/hour: cheaper than /discover/landscape's multi-stage pipeline (a
# handful of embed calls, not a multi-stage generate pipeline) but still
# calls out to a provider on every request -- SECURITY.md's per-user limits
# on expensive endpoints, same reasoning as /papers/{id}/assistant's 30/hour.
@limiter.limit("20/hour", key_func=rate_limit_key)
async def get_recommendations(
    request: Request,
    provider_id: str,
    embed_model: str,
    endpoint: str | None = None,
    # api_key deliberately taken from a header, not a query parameter,
    # despite API_SPEC.md sketching this as a plain `?provider_id=...&
    # api_key=...` GET -- a secret in the URL query string is trivially
    # captured by access logs, reverse-proxy logs, and browser history,
    # which conflicts with this project's "API keys ... never logged" rule
    # (CLAUDE.md/SECURITY.md). Still a GET, still not SSE -- only the
    # transport of this one sensitive field changed.
    x_provider_api_key: str | None = Header(default=None, alias="X-Provider-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RecommendationItem]:
    try:
        return await discovery_service.run_recommendations(
            db,
            current_user.id,
            provider_id=provider_id,
            api_key=x_provider_api_key,
            endpoint=endpoint,
            embed_model=embed_model,
        )
    except NotImplementedError as exc:
        # build_provider raises bare NotImplementedError (not an AppError)
        # for a catalogued-but-not-yet-adapted provider id -- translate it so
        # this still returns the shared error envelope instead of falling
        # through to FastAPI's generic 500.
        raise InvalidConfigError(str(exc)) from exc


# --- roadmap / prerequisite graph (Phase 6) ---------------------------------


@router.post("/roadmap")
# 5/hour matches /discover/landscape's ceiling -- a comparably expensive
# multi-stage pipeline (milestone search, concept extraction per milestone,
# prerequisite mapping, overview generation -- several provider round-trips).
@limiter.limit("5/hour", key_func=rate_limit_key)
async def create_roadmap(
    request: Request,
    body: RoadmapCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Streams ``AnalysisEvent``s as SSE, same format/pre-flight-peek pattern
    as ``create_landscape``.

    A ``"paper"`` target's ownership is checked with the request's own
    session *before* the stream starts -- a real 404 JSON response, same
    non-leaking pattern as every other owned-resource route (``get_owned_paper``),
    rather than an SSE stream that already committed to a 200 status only to
    report the failure as a stream event.
    """
    if isinstance(body.target, RoadmapPaperTarget):
        await get_owned_paper(db, body.target.paper_id, current_user.id)

    logger.info("roadmap_generation_started user_id=%s target_type=%s", current_user.id, body.target.type)

    events = discovery_service.run_roadmap_generation(
        user_id=current_user.id,
        target=body.target,
        provider_id=body.provider_id,
        api_key=body.api_key,
        endpoint=body.endpoint,
        model=body.model,
        embed_model=body.embed_model,
    )

    try:
        first_event: discovery_service.AnalysisEvent | None = await events.__anext__()
    except StopAsyncIteration:
        first_event = None

    async def _stream() -> AsyncIterator[bytes]:
        if first_event is not None:
            yield _format_sse_event(first_event)
        async for event in events:
            yield _format_sse_event(event)

    return StreamingResponse(_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/roadmap/{roadmap_id}", response_model=RoadmapResponse)
async def get_roadmap(
    roadmap_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Roadmap:
    return await discovery_service.get_owned_roadmap(db, roadmap_id, current_user.id)


@router.get("/roadmaps", response_model=list[RoadmapSummary])
async def list_roadmaps(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RoadmapSummary]:
    roadmaps = await discovery_service.list_roadmaps(db, current_user.id)
    return [discovery_service.build_roadmap_summary(roadmap) for roadmap in roadmaps]


@router.patch("/roadmap/{roadmap_id}/milestones/{milestone_id}", response_model=RoadmapResponse)
async def update_roadmap_milestone(
    roadmap_id: uuid.UUID,
    milestone_id: str,
    body: MilestoneUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Roadmap:
    return await discovery_service.update_milestone_status(db, roadmap_id, current_user.id, milestone_id, body.status)
