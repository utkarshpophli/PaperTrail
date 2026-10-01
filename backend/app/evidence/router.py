"""Evidence routes: analysis (SSE), evidence retrieval, and per-claim
lookup/reverification.

Router lives in this domain package, same module-owns-its-router pattern as
``app.papers.router``/``app.providers.router``. Extraction/verification
logic itself lives in ``app.evidence.service`` (rag-engineer) — this module
only enforces auth/ownership/rate-limits and adapts that service's output to
SSE / the shared error envelope, same division of labor as
``app.providers.router`` calling into ``app.providers.registry``.

The service module is imported as a module (``from app.evidence import
service as evidence_service``), not as individual names, specifically so
tests can ``monkeypatch.setattr("app.evidence.service.run_analysis", ...)``
etc. and have this router see the patched version — same pattern
``app.providers.router`` uses for ``app.providers.registry.build_provider``.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Literal, Self

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.logging import get_logger
from app.core.rate_limit import limiter, rate_limit_key
from app.db.session import get_db
from app.evidence import service as evidence_service
from app.evidence.exceptions import ClaimNotFoundError
from app.evidence.figures import FigureResponse
from app.evidence.schemas import (
    ClaimResponse,
    EvidenceResponse,
    GeneratedSectionResponse,
    LearningResponse,
    StageConfig,
)
from app.evidence.story_visuals import StorySpecResponse
from app.models.claim import Claim
from app.models.user import User
from app.papers.service import get_owned_paper

logger = get_logger(__name__)
router = APIRouter(prefix="/papers", tags=["evidence"])


class AnalyzeRequest(BaseModel):
    """Multi-stage analysis request per API_SPEC.md's ``POST
    /papers/{id}/analyze`` docstring: a provider/model assignment per stage
    (``"evidence"`` | ``"technical"`` | ``"report"`` | ``"visual"``).

    Phase 2 shipped a flat single-stage body (``{provider_id, api_key, ...}``
    implicitly meaning evidence-only). This is a clean breaking change, not a
    backward-compatible superset: ``phase-0-foundation`` (which is the only
    branch that ever had the flat shape) is not merged into ``master``, so
    there are no real external callers of the old shape to preserve --
    keeping both would just be permanent complexity for a request format
    that was never released.
    """

    stages: dict[str, StageConfig]


class AssistantRequest(BaseModel):
    """Body for ``POST /papers/{id}/assistant`` per API_SPEC.md's Research
    Assistant section. ``compare_with`` is required (non-empty) for
    ``action == "compare"`` and forbidden for every other action -- same
    exactly-one-shape-per-mode validation style as
    ``ArxivResolveRequest._exactly_one_identifier`` (Phase 1).

    Router-local (not in ``app.evidence.schemas``) because, unlike
    ``StageConfig``, nothing in ``app.evidence.service`` needs this exact
    shape -- ``run_assistant`` takes its fields as plain keyword arguments.
    """

    action: Literal["understand", "deep-dive", "challenge", "compare", "verify", "implement", "research", "learn"]
    # max_length matches the narrative-field length precedent (service.py's
    # _NARRATIVE_MAX_LENGTH) -- security review LOW: an uncapped question
    # isn't a prompt-injection bypass (wrap_prompt's structural fencing
    # holds regardless of its content), but it inflates every provider call
    # this session makes, including a local model's per-call compute.
    question: str | None = Field(default=None, max_length=4000)
    # max_length=5: security review MEDIUM -- each entry drives ~4 sequential
    # DB round-trips (ownership check, paper/evidence lookup, claim load) in
    # both the router's ownership loop and run_assistant, none concurrent.
    # An unbounded list is a per-request DB-fan-out DoS shape distinct from
    # (already-correct) unauthorized-access control. 5 is generous for
    # "compare this paper against a few others."
    compare_with: list[uuid.UUID] | None = Field(default=None, max_length=5)
    provider_id: str
    api_key: str | None = None
    endpoint: str | None = None
    model: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _compare_with_matches_action(self) -> Self:
        has_compare_with = bool(self.compare_with)
        if self.action == "compare" and not has_compare_with:
            raise ValueError("action 'compare' requires a non-empty compare_with")
        if self.action != "compare" and has_compare_with:
            raise ValueError("compare_with is only valid when action is 'compare'")
        return self


def _format_sse_event(event: "evidence_service.AnalysisEvent") -> bytes:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n".encode("utf-8")


def _find_owned_claim(evidence: EvidenceResponse, claim_id: uuid.UUID) -> ClaimResponse:
    # ponytail: linear scan over one paper's claims rather than a dedicated
    # get_claim(db, paper_id, claim_id) service function — reuses
    # get_evidence's already-enforced paper ownership instead of a second DB
    # access path, and a paper's claim count is expected to be small (tens,
    # not thousands). Add a dedicated lookup if that stops being true.
    for claim in evidence.claims:
        if claim.id == claim_id:
            return claim
    raise ClaimNotFoundError("Claim not found")


@router.post("/{paper_id}/analyze")
# 5/hour kept unchanged from Phase 2 despite a single request now being able
# to request all three stages (evidence + technical + report) — a conscious
# call (security review, Phase 4a), not an accidental byproduct of the
# multi-stage rewrite: worst case is 5 full-pipeline runs/hour/user, judged
# an acceptable cost ceiling for now. Revisit with a stage-weighted limit if
# real usage shows otherwise.
@limiter.limit("5/hour", key_func=rate_limit_key)
async def analyze_paper(
    request: Request,
    paper_id: uuid.UUID,
    body: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Streams ``AnalysisEvent``s as SSE (`event: {type}\\ndata: {json}\\n\\n`),
    tagged per-stage via each event's ``stage`` field.

    Never logs any ``StageConfig.api_key`` — only paper/user ids and the
    requested stage names, same credential-handling discipline as
    ``app.providers.router``.
    """
    await get_owned_paper(db, paper_id, current_user.id)
    logger.info(
        "analysis_started paper_id=%s user_id=%s stages=%s", paper_id, current_user.id, list(body.stages.keys())
    )

    events = evidence_service.run_analysis(paper_id=paper_id, stages=body.stages)

    # Peek the first event outside the streamed body: StreamingResponse
    # commits status 200 + headers before pulling its first chunk, so a
    # pre-flight failure (e.g. PaperNotParsedError, or EvidenceNotFoundError
    # when technical/report is requested without evidence ever having run)
    # raised on the generator's first step must be awaited here to surface as
    # a normal typed-error JSON response instead of an SSE stream that
    # already claimed success.
    try:
        first_event: evidence_service.AnalysisEvent | None = await events.__anext__()
    except StopAsyncIteration:
        first_event = None

    async def _stream() -> AsyncIterator[bytes]:
        if first_event is not None:
            yield _format_sse_event(first_event)
        async for event in events:
            yield _format_sse_event(event)

    return StreamingResponse(_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/{paper_id}/assistant")
# 30/hour vs. /analyze's 5/hour: the Research Assistant is meant to feel like
# responsive Q&A over evidence that already exists (one targeted action per
# call), not a multi-stage extraction/generation pipeline run -- a much
# cheaper per-call cost, so a noticeably higher ceiling is appropriate, while
# still bounding the per-user cost of an endpoint that calls out to a
# provider on every request (SECURITY.md: per-user limits on expensive
# endpoints).
@limiter.limit("30/hour", key_func=rate_limit_key)
async def assistant_paper(
    request: Request,
    paper_id: uuid.UUID,
    body: AssistantRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Streams ``AnalysisEvent``s as SSE, same format/pre-flight-peek pattern
    as ``analyze_paper``.

    ``compare_with`` lets a request reference OTHER papers by id -- every
    single one of them is ownership-checked here (individually, same
    ``get_owned_paper`` call as the primary paper) before ``run_assistant``
    is ever invoked, which trusts the caller to have already done so. A
    non-owned id anywhere in the list fails the whole request with the same
    ``paper_not_found`` 404 as the primary paper -- never leaks which id in
    the list was the problem, never partially proceeds.

    Never logs any ``api_key`` -- same credential-handling discipline as
    ``analyze_paper``.
    """
    await get_owned_paper(db, paper_id, current_user.id)
    for compare_paper_id in body.compare_with or []:
        await get_owned_paper(db, compare_paper_id, current_user.id)

    logger.info(
        "assistant_started paper_id=%s user_id=%s action=%s compare_with=%s",
        paper_id,
        current_user.id,
        body.action,
        body.compare_with,
    )

    events = evidence_service.run_assistant(
        paper_id=paper_id,
        action=body.action,
        question=body.question,
        compare_with=body.compare_with,
        provider_id=body.provider_id,
        api_key=body.api_key,
        endpoint=body.endpoint,
        model=body.model,
    )

    # Same pre-flight-peek rationale as analyze_paper: a pre-flight failure
    # (e.g. EvidenceNotFoundError when the primary paper or a compare_with
    # paper lacks evidence) raised on the generator's first step must be
    # awaited here to surface as a normal typed-error JSON response instead
    # of a corrupted 200 SSE stream.
    try:
        first_event: evidence_service.AnalysisEvent | None = await events.__anext__()
    except StopAsyncIteration:
        first_event = None

    async def _stream() -> AsyncIterator[bytes]:
        if first_event is not None:
            yield _format_sse_event(first_event)
        async for event in events:
            yield _format_sse_event(event)

    return StreamingResponse(_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/{paper_id}/evidence", response_model=EvidenceResponse)
async def get_paper_evidence(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvidenceResponse:
    await get_owned_paper(db, paper_id, current_user.id)
    return await evidence_service.get_evidence(db, paper_id)


@router.get("/{paper_id}/report", response_model=list[GeneratedSectionResponse])
async def get_paper_report(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GeneratedSectionResponse]:
    """Raises ``ReportNotFoundError`` (404) if the report stage hasn't been
    generated yet -- distinct from the paper itself not existing/not owned,
    which ``get_owned_paper`` already surfaces as ``paper_not_found``."""
    await get_owned_paper(db, paper_id, current_user.id)
    return await evidence_service.get_report(db, paper_id)


@router.get("/{paper_id}/technical-appendix", response_model=list[GeneratedSectionResponse])
async def get_paper_technical_appendix(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GeneratedSectionResponse]:
    """Raises ``TechnicalAppendixNotFoundError`` (404) if the technical stage
    hasn't been generated yet for this paper."""
    await get_owned_paper(db, paper_id, current_user.id)
    return await evidence_service.get_technical_appendix(db, paper_id)


@router.get("/{paper_id}/story", response_model=list[GeneratedSectionResponse])
async def get_paper_story(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GeneratedSectionResponse]:
    """Raises ``StoryNotFoundError`` (404) if the visual stage hasn't been
    generated yet for this paper -- same not-generated-yet pattern as
    ``get_paper_report``/``get_paper_technical_appendix``."""
    await get_owned_paper(db, paper_id, current_user.id)
    return await evidence_service.get_story(db, paper_id)


@router.get("/{paper_id}/story-spec", response_model=StorySpecResponse)
async def get_paper_story_spec(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StorySpecResponse:
    """The typed StorySpec (meta + sections with visuals). Raises
    ``StoryNotFoundError`` (404 ``story_not_found``) when none exists -- also
    for a legacy story generated before typed visuals, which ``/story`` still
    serves."""
    await get_owned_paper(db, paper_id, current_user.id)
    return await evidence_service.get_story_spec(db, paper_id)


@router.get("/{paper_id}/figures", response_model=list[FigureResponse])
async def get_paper_figures(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FigureResponse]:
    """Extracted PDF figures with their label, why-it-matters text and linked
    claims. Unlinked figures still appear. Image bytes are served by
    ``GET /papers/{id}/figures/{filename}``."""
    await get_owned_paper(db, paper_id, current_user.id)
    return await evidence_service.get_figures(db, paper_id)


@router.get("/{paper_id}/learning", response_model=LearningResponse)
async def get_paper_learning(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LearningResponse:
    """Raises ``LearningNotFoundError`` (404) if the visual stage hasn't been
    generated yet for this paper."""
    await get_owned_paper(db, paper_id, current_user.id)
    return await evidence_service.get_learning(db, paper_id)


@router.post("/{paper_id}/implementation-plan", response_model=list[GeneratedSectionResponse])
# 10/hour: one provider round-trip per call (plus, at most, one best-effort
# GitHub README fetch) -- heavier than plain CRUD but not a multi-stage
# pipeline like /analyze (5/hour), so a ceiling between that and
# /repositories/detect's 20/hour (SECURITY.md: per-user limits on endpoints
# that call out to an external provider/API).
@limiter.limit("10/hour", key_func=rate_limit_key)
async def generate_paper_implementation_plan(
    request: Request,
    paper_id: uuid.UUID,
    body: StageConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GeneratedSectionResponse]:
    """Plain request/response, not SSE -- this is one generation call over
    already-persisted evidence, not a multi-stage pipeline with progress to
    stream. Never logs ``body.api_key`` -- same credential-handling
    discipline as ``analyze_paper``.
    """
    await get_owned_paper(db, paper_id, current_user.id)
    logger.info("implementation_plan_requested paper_id=%s user_id=%s", paper_id, current_user.id)
    return await evidence_service.generate_implementation_plan(
        db,
        paper_id,
        provider_id=body.provider_id,
        api_key=body.api_key,
        endpoint=body.endpoint,
        model=body.model,
    )


@router.get("/{paper_id}/implementation-plan", response_model=list[GeneratedSectionResponse])
async def get_paper_implementation_plan(
    paper_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GeneratedSectionResponse]:
    """Raises ``ImplementationPlanNotFoundError`` (404) if it hasn't been
    generated yet for this paper."""
    await get_owned_paper(db, paper_id, current_user.id)
    return await evidence_service.get_implementation_plan(db, paper_id)


@router.get("/{paper_id}/claims/{claim_id}", response_model=ClaimResponse)
async def get_claim(
    paper_id: uuid.UUID,
    claim_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    await get_owned_paper(db, paper_id, current_user.id)
    evidence = await evidence_service.get_evidence(db, paper_id)
    return _find_owned_claim(evidence, claim_id)


@router.post("/{paper_id}/claims/{claim_id}/reverify", response_model=ClaimResponse)
async def reverify_paper_claim(
    paper_id: uuid.UUID,
    claim_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Claim:
    # reverify_claim returns the ORM Claim row (like app.papers.router's
    # get_paper returns the ORM Paper) -- response_model=ClaimResponse above
    # handles the API-shape conversion via from_attributes.
    await get_owned_paper(db, paper_id, current_user.id)
    evidence = await evidence_service.get_evidence(db, paper_id)
    _find_owned_claim(evidence, claim_id)  # ownership/existence check before the (cheap) reverify side effect
    logger.info("claim_reverify_requested paper_id=%s claim_id=%s user_id=%s", paper_id, claim_id, current_user.id)
    return await evidence_service.reverify_claim(db, claim_id)
