"""Public entrypoints for the Discovery module -- the contract
``backend-engineer``/frontend build the discover routes against.

``run_landscape_search`` owns its own DB session (like
``app.evidence.service.run_analysis``) because it's a long-running generator
driving an SSE response, not bound to one request's session lifecycle.
Everything else takes a request-scoped ``AsyncSession`` like any other
route-backing service call.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections import service as collections_service
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.discovery.clustering import cluster_landscape
from app.discovery.concepts import ground_concepts_from_arxiv_candidate, ground_concepts_from_paper
from app.discovery.exceptions import (
    ClusterReferencesUnknownPaperError,
    EmptyTopicSearchResultError,
    InvalidMilestoneStatusError,
    InvalidPromoteTargetError,
    InvalidRoadmapTargetError,
    MilestoneNotFoundError,
    RoadmapNotFoundError,
    TopicLandscapeNotFoundError,
)
from app.discovery.extraction import extract_paper_cards
from app.discovery.prerequisites import propose_prerequisite_edges
from app.discovery.ranking import (
    RankedPaper,
    RankedRecommendation,
    rank_candidates_by_topic,
    rank_candidates_for_profile,
)
from app.discovery.roadmap import (
    MilestoneDraft,
    compute_concept_depths,
    generate_roadmap_overview,
    select_milestone_candidates_for_paper,
    select_milestone_candidates_for_topic,
    sequence_milestones,
)
from app.discovery.schemas import (
    Concept,
    GraphEdge,
    GraphNode,
    LandscapeClusteringOutput,
    LandscapeGraphResponse,
    LandscapePaperItem,
    Milestone,
    PaperExtractionCard,
    PrerequisiteEdge,
    RecommendationItem,
    RoadmapPaperTarget,
    RoadmapResponse,
    RoadmapSummary,
    RoadmapTarget,
    RoadmapTopicTarget,
    TopicLandscapeResponse,
)
from app.models.collection import Collection
from app.models.paper import Paper
from app.models.profile import Profile
from app.models.roadmap import Roadmap
from app.models.topic_landscape import TopicLandscape
from app.papers.arxiv_client import ArxivMetadata, search_arxiv_topic
from app.papers.exceptions import ArxivUnavailableError
from app.providers.base import AIProvider
from app.providers.errors import (
    AuthenticationError,
    InvalidConfigError,
    NotSupportedError,
    ProviderUnavailableError,
    StructuredOutputError,
)
from app.providers.exceptions import ProviderNotFoundError
from app.providers.ping import ping_chat, ping_embed
from app.providers.redaction import redacting
from app.providers.registry import build_provider

logger = get_logger(__name__)

_ALLOWED_MILESTONE_STATUSES = {"locked", "available", "completed", "skipped"}

_TOP_N_CANDIDATES = 15
_MAX_ARXIV_RESULTS = 30
_MAX_INTEREST_QUERY_TERMS = 5
_ARXIV_RESULTS_PER_INTEREST = 10

_CLUSTER_COLOR_PALETTE = ["#6366f1", "#22c55e", "#f97316", "#ec4899", "#06b6d4"]
_UNCLUSTERED_COLOR = "#9ca3af"


class AnalysisEvent(BaseModel):
    """Same ``{type, stage, message, data}`` SSE event shape as
    ``app.evidence.service.AnalysisEvent`` -- a separate class (not imported)
    so Discovery stays decoupled from the Evidence Engine module boundary
    per ARCHITECTURE.md ("isolated so MVP ships without them and they attach
    later without touching the Evidence Engine")."""

    type: Literal["progress", "checkpoint", "error", "done"]
    stage: str | None = None
    message: str | None = None
    data: dict | None = None


# --- topic landscape ---------------------------------------------------


async def run_landscape_search(
    *,
    user_id: uuid.UUID,
    topic: str,
    provider_id: str,
    api_key: str | None,
    endpoint: str | None,
    model: str,
    embed_model: str,
) -> AsyncIterator[AnalysisEvent]:
    """Runs the full topic-landscape pipeline: arXiv search -> embedding
    re-rank -> per-paper extraction -> clustering -> persistence. Every
    stage failure is emitted as a ``type="error"`` event (never raised, so
    the SSE stream always completes cleanly) -- same discipline as
    ``app.evidence.service``'s stage functions.
    """
    yield AnalysisEvent(type="progress", stage="landscape", message="Configuring AI provider")
    try:
        provider: AIProvider = redacting(build_provider(provider_id, api_key=api_key, endpoint=endpoint), api_key)
    except (ProviderNotFoundError, InvalidConfigError, NotImplementedError) as exc:
        logger.warning("landscape_provider_setup_failed user_id=%s error=%s", user_id, exc)
        yield AnalysisEvent(type="error", stage="landscape", message=str(exc))
        return

    yield AnalysisEvent(type="progress", stage="landscape", message="Checking model availability")
    try:
        await ping_chat(provider, model)
        await ping_embed(provider, embed_model)
    except (AuthenticationError, ProviderUnavailableError, NotSupportedError, StructuredOutputError) as exc:
        logger.warning("landscape_model_preflight_failed user_id=%s provider=%s error=%s", user_id, provider_id, exc)
        yield AnalysisEvent(type="error", stage="landscape", message=str(exc))
        return

    yield AnalysisEvent(type="progress", stage="landscape", message="Querying arXiv")
    try:
        candidates = await search_arxiv_topic(topic, max_results=_MAX_ARXIV_RESULTS)
    except ArxivUnavailableError as exc:
        logger.warning("landscape_arxiv_search_failed user_id=%s error=%s", user_id, exc)
        yield AnalysisEvent(type="error", stage="landscape", message=str(exc))
        return

    if not candidates:
        empty_result_error = EmptyTopicSearchResultError(f"No arXiv results found for topic {topic!r}")
        logger.info("landscape_empty_result user_id=%s topic=%s", user_id, topic)
        yield AnalysisEvent(type="error", stage="landscape", message=empty_result_error.message)
        return

    yield AnalysisEvent(type="checkpoint", stage="landscape", data={"candidates": len(candidates)})

    yield AnalysisEvent(type="progress", stage="landscape", message="Ranking by relevance")
    try:
        ranked = await rank_candidates_by_topic(
            provider, topic, candidates, embed_model=embed_model, top_n=_TOP_N_CANDIDATES
        )
    except NotSupportedError as exc:
        logger.warning("landscape_ranking_failed user_id=%s provider=%s error=%s", user_id, provider_id, exc)
        yield AnalysisEvent(type="error", stage="landscape", message=str(exc))
        return

    yield AnalysisEvent(type="checkpoint", stage="landscape", data={"ranked": len(ranked)})

    ranked_papers = [item.paper for item in ranked]
    yield AnalysisEvent(type="progress", stage="landscape", message="Extracting summaries")
    try:
        cards = await extract_paper_cards(provider, ranked_papers, model=model)
    except (StructuredOutputError, ProviderUnavailableError, AuthenticationError, NotSupportedError) as exc:
        logger.warning("landscape_extraction_failed user_id=%s provider=%s error=%s", user_id, provider_id, exc)
        yield AnalysisEvent(type="error", stage="landscape", message=str(exc))
        return

    yield AnalysisEvent(type="checkpoint", stage="landscape", data={"extracted": len(cards)})

    yield AnalysisEvent(type="progress", stage="landscape", message="Mapping landscape")
    try:
        clustering = await cluster_landscape(provider, ranked_papers, cards, model=model)
    except (
        StructuredOutputError,
        ProviderUnavailableError,
        AuthenticationError,
        NotSupportedError,
        ClusterReferencesUnknownPaperError,
    ) as exc:
        logger.warning("landscape_clustering_failed user_id=%s provider=%s error=%s", user_id, provider_id, exc)
        yield AnalysisEvent(type="error", stage="landscape", message=str(exc))
        return

    async with AsyncSessionLocal() as db:
        landscape = await _persist_landscape(db, user_id, topic, ranked, cards, clustering)
        response = TopicLandscapeResponse.model_validate(landscape)

    yield AnalysisEvent(type="checkpoint", stage="landscape", data={"clusters": len(clustering.clusters)})
    yield AnalysisEvent(type="done", stage="landscape", data=response.model_dump(mode="json"))


async def _persist_landscape(
    db: AsyncSession,
    user_id: uuid.UUID,
    topic: str,
    ranked: list[RankedPaper],
    cards: list[PaperExtractionCard],
    clustering: LandscapeClusteringOutput,
) -> TopicLandscape:
    cluster_rows = [
        {
            "id": str(uuid.uuid4()),
            "label": cluster.label,
            "description": cluster.description,
            "paper_ids": list(cluster.arxiv_ids),
        }
        for cluster in clustering.clusters
    ]
    # First cluster that claims a given arxiv_id wins -- the clustering
    # prompt asks for exactly one assignment per paper, but nothing enforces
    # that server-side beyond this deterministic tie-break (a paper claimed
    # by two clusters is a prompt-following slip, not a validation error
    # worth failing the whole batch over).
    cluster_id_by_arxiv_id: dict[str, str] = {}
    for cluster_row in cluster_rows:
        for arxiv_id in cluster_row["paper_ids"]:
            cluster_id_by_arxiv_id.setdefault(arxiv_id, cluster_row["id"])

    paper_rows = [
        LandscapePaperItem(
            arxiv_id=item.paper.arxiv_id,
            title=item.paper.title,
            authors=item.paper.authors,
            year=item.paper.year,
            pdf_url=item.paper.pdf_url,
            abstract=item.paper.abstract,
            relevance_score=item.relevance_score,
            cluster_id=cluster_id_by_arxiv_id.get(item.paper.arxiv_id),
            extraction=card,
        ).model_dump(mode="json")
        for item, card in zip(ranked, cards, strict=True)
    ]

    landscape = TopicLandscape(
        user_id=user_id,
        topic=topic,
        overview=clustering.overview,
        papers=paper_rows,
        clusters=cluster_rows,
    )
    db.add(landscape)
    await db.commit()
    await db.refresh(landscape)
    return landscape


async def get_owned_landscape(db: AsyncSession, landscape_id: uuid.UUID, user_id: uuid.UUID) -> TopicLandscape:
    """Fetches a landscape only if it belongs to ``user_id`` -- a landscape
    owned by someone else looks identical to a missing one, same row-level
    authorization discipline as ``app.papers.service.get_owned_paper``."""
    landscape = await db.scalar(
        select(TopicLandscape).where(TopicLandscape.id == landscape_id, TopicLandscape.user_id == user_id)
    )
    if landscape is None:
        raise TopicLandscapeNotFoundError("Topic landscape not found")
    return landscape


def _color_for_cluster_index(index: int) -> str:
    return _CLUSTER_COLOR_PALETTE[index % len(_CLUSTER_COLOR_PALETTE)]


def build_landscape_graph(landscape: TopicLandscape) -> LandscapeGraphResponse:
    """Builds the Neural Map's ``{nodes, edges}`` contract (ARCHITECTURE.md's
    Phase 5 decisions) from a persisted landscape.

    Edges connect every pair of papers within the same cluster (not a
    similarity-threshold subset) -- simplest deterministic choice given that
    pairwise candidate-to-candidate cosine similarity isn't persisted
    anywhere (only each candidate's similarity to the topic string is), so
    ``weight`` is always ``None`` here. ``size`` is each paper's
    topic-relevance score, giving the frontend a meaningful default without
    it needing a second call.
    """
    cluster_index_by_id = {cluster["id"]: index for index, cluster in enumerate(landscape.clusters)}

    nodes = [
        GraphNode(
            id=paper["arxiv_id"],
            label=paper["title"],
            color=(
                _color_for_cluster_index(cluster_index_by_id[paper["cluster_id"]])
                if paper.get("cluster_id") in cluster_index_by_id
                else _UNCLUSTERED_COLOR
            ),
            size=paper.get("relevance_score"),
        )
        for paper in landscape.papers
    ]

    edges: list[GraphEdge] = []
    for cluster in landscape.clusters:
        paper_ids = cluster["paper_ids"]
        for i in range(len(paper_ids)):
            for j in range(i + 1, len(paper_ids)):
                edges.append(GraphEdge(source=paper_ids[i], target=paper_ids[j]))

    return LandscapeGraphResponse(nodes=nodes, edges=edges)


async def promote_landscape(
    db: AsyncSession,
    user_id: uuid.UUID,
    landscape_id: uuid.UUID,
    collection_id: uuid.UUID | None,
    collection_name: str | None,
) -> tuple[Collection, list[str], list[str]]:
    """Copies a landscape's papers into a new or existing ``Collection``
    (the route Phase 5 deferred -- see ARCHITECTURE.md's Phase 7 decisions).

    Only landscape papers that are already an ingested, owned ``Paper`` row
    (matched by ``arxiv_id``) are added -- ``Collection.paper_ids`` holds
    real owned ``Paper`` UUIDs everywhere else in this schema's convention,
    so a candidate the user hasn't ingested yet is reported back as skipped
    rather than turned into a bare arxiv_id string or a silently-invented
    ``Paper`` row.
    """
    landscape = await get_owned_landscape(db, landscape_id, user_id)

    if collection_id is not None:
        collection = await collections_service.get_owned_collection(db, collection_id, user_id)
    elif collection_name:
        collection = await collections_service.create_collection(db, user_id, collection_name)
    else:
        raise InvalidPromoteTargetError("Either collection_id or collection_name is required")

    arxiv_ids = [paper["arxiv_id"] for paper in landscape.papers]
    owned_papers = await db.scalars(select(Paper).where(Paper.user_id == user_id, Paper.arxiv_id.in_(arxiv_ids)))
    owned_by_arxiv_id = {paper.arxiv_id: paper for paper in owned_papers.all()}

    added: list[str] = []
    skipped: list[str] = []
    for arxiv_id in arxiv_ids:
        owned = owned_by_arxiv_id.get(arxiv_id)
        if owned is None:
            skipped.append(arxiv_id)
            continue
        collection = await collections_service.add_paper_to_collection(db, collection, owned.id)
        added.append(arxiv_id)

    return collection, added, skipped


# --- profile -------------------------------------------------------------


async def get_or_create_profile(db: AsyncSession, user_id: uuid.UUID) -> Profile:
    """Lazily defaults a profile on first read/use -- ARCHITECTURE.md's
    Phase 5 decisions: "defaulted lazily if none exists yet"."""
    profile = await db.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is not None:
        return profile
    profile = Profile(user_id=user_id, interests=[], level="beginner", goals=[])
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def update_profile(
    db: AsyncSession, user_id: uuid.UUID, interests: list[str], level: str, goals: list[str]
) -> Profile:
    profile = await get_or_create_profile(db, user_id)
    profile.interests = interests
    profile.level = level
    profile.goals = goals
    await db.commit()
    await db.refresh(profile)
    return profile


# --- recommendations -------------------------------------------------------


async def _owned_arxiv_ids(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    """The user's own uploaded papers, by arxiv_id -- the "reading history"
    proxy documented in ARCHITECTURE.md's Phase 5 decisions (no separate
    view-tracking model). Used here only to avoid recommending a paper the
    user already has, not as a deeper personalization signal."""
    rows = await db.scalars(select(Paper.arxiv_id).where(Paper.user_id == user_id, Paper.arxiv_id.is_not(None)))
    return {row for row in rows.all() if row}


def _build_explanation(item: RankedRecommendation) -> str:
    return (
        f'Ranked for its similarity to the {item.matched_signal_kind} on your profile: '
        f'"{item.matched_signal_text}" (similarity {item.relevance_score:.2f}).'
    )


async def run_recommendations(
    db: AsyncSession,
    user_id: uuid.UUID,
    provider_id: str,
    api_key: str | None,
    endpoint: str | None,
    embed_model: str,
) -> list[RecommendationItem]:
    """Not a generator/SSE (API_SPEC.md: a handful of embed calls, not a
    multi-stage pipeline) -- typed errors (``ProviderNotFoundError``,
    ``NotSupportedError``, ``ArxivUnavailableError``, etc, all ``AppError``
    subclasses) propagate to the router's caller, handled uniformly by
    ``app.main``'s ``AppError`` handler.
    """
    profile = await get_or_create_profile(db, user_id)
    if not profile.interests and not profile.goals:
        return []

    provider: AIProvider = redacting(build_provider(provider_id, api_key=api_key, endpoint=endpoint), api_key)

    owned_arxiv_ids = await _owned_arxiv_ids(db, user_id)

    candidates: list[ArxivMetadata] = []
    seen_ids: set[str] = set()
    for interest in profile.interests[:_MAX_INTEREST_QUERY_TERMS]:
        results = await search_arxiv_topic(interest, max_results=_ARXIV_RESULTS_PER_INTEREST)
        for candidate in results:
            if candidate.arxiv_id and candidate.arxiv_id not in seen_ids and candidate.arxiv_id not in owned_arxiv_ids:
                seen_ids.add(candidate.arxiv_id)
                candidates.append(candidate)

    if not candidates:
        return []

    ranked = await rank_candidates_for_profile(provider, profile.interests, profile.goals, candidates, embed_model=embed_model)

    return [
        RecommendationItem(
            arxiv_id=item.paper.arxiv_id,
            title=item.paper.title,
            authors=item.paper.authors,
            year=item.paper.year,
            abstract=item.paper.abstract,
            relevance_score=item.relevance_score,
            explanation=_build_explanation(item),
        )
        for item in ranked
    ]


# --- roadmap / prerequisite graph (Phase 6) ---------------------------------


@dataclass(frozen=True)
class _MilestoneSource:
    """Exactly one of ``paper``/``candidate`` is set -- an owned anchor paper
    (grounded via its own ``GlossaryTerm`` rows) or an arXiv search result
    (grounded via ``ground_concepts_from_paper`` if the user happens to
    already own it with evidence, else via abstract extraction)."""

    paper: Paper | None
    candidate: ArxivMetadata | None


async def _ground_milestone_candidate(
    db: AsyncSession,
    provider: AIProvider,
    user_id: uuid.UUID,
    candidate: ArxivMetadata,
    model: str,
) -> tuple[uuid.UUID | None, list[Concept]]:
    """Grounds one arXiv-candidate milestone's concepts. Prefers the user's
    own already-analyzed copy (real ``GlossaryTerm`` rows, no LLM call) over
    abstract extraction, per ARCHITECTURE.md's Phase 6 decisions -- a
    milestone whose paper is already owned links to real evidence, not a
    second parallel abstract-only extraction of a paper already ingested.
    """
    owned = await db.scalar(select(Paper).where(Paper.user_id == user_id, Paper.arxiv_id == candidate.arxiv_id))
    if owned is not None:
        concepts = await ground_concepts_from_paper(db, owned.id)
        if concepts:
            return owned.id, concepts
    concepts = await ground_concepts_from_arxiv_candidate(
        provider, arxiv_id=candidate.arxiv_id, title=candidate.title, abstract=candidate.abstract, model=model
    )
    return None, concepts


async def _build_milestone_drafts(
    db: AsyncSession,
    provider: AIProvider,
    user_id: uuid.UUID,
    sources: list[_MilestoneSource],
    model: str,
) -> tuple[list[MilestoneDraft], list[Concept]]:
    """Sequential, not concurrent (unlike ``extract_paper_cards``) --
    ponytail: a roadmap has at most ``_MILESTONE_COUNT_BEGINNER`` (8) sources,
    small enough that the concurrency-cancellation bookkeeping isn't worth it
    yet; parallelize the same way if roadmap generation latency becomes a
    measured problem.
    """
    drafts: list[MilestoneDraft] = []
    all_concepts: list[Concept] = []
    for source in sources:
        if source.paper is not None:
            paper_id: uuid.UUID | None = source.paper.id
            arxiv_id = source.paper.arxiv_id
            title = source.paper.title
            concepts = await ground_concepts_from_paper(db, source.paper.id)
        else:
            assert source.candidate is not None
            arxiv_id = source.candidate.arxiv_id
            title = source.candidate.title
            paper_id, concepts = await _ground_milestone_candidate(db, provider, user_id, source.candidate, model)
        drafts.append(
            MilestoneDraft(
                id=str(uuid.uuid4()),
                paper_id=paper_id,
                arxiv_id=arxiv_id,
                title=title,
                concept_ids=[concept.id for concept in concepts],
            )
        )
        all_concepts.extend(concepts)
    return drafts, all_concepts


async def _persist_roadmap(
    db: AsyncSession,
    user_id: uuid.UUID,
    target_description: str,
    target_paper_id: uuid.UUID | None,
    concepts: list[Concept],
    edges: list[PrerequisiteEdge],
    milestones: list[Milestone],
    overview: str,
) -> Roadmap:
    roadmap = Roadmap(
        user_id=user_id,
        target_description=target_description,
        target_paper_id=target_paper_id,
        concepts=[concept.model_dump(mode="json") for concept in concepts],
        edges=[edge.model_dump(mode="json") for edge in edges],
        milestones=[milestone.model_dump(mode="json") for milestone in milestones],
        overview=overview,
    )
    db.add(roadmap)
    await db.commit()
    await db.refresh(roadmap)
    return roadmap


async def run_roadmap_generation(
    *,
    user_id: uuid.UUID,
    target: RoadmapTarget,
    provider_id: str,
    api_key: str | None,
    endpoint: str | None,
    model: str,
    embed_model: str,
) -> AsyncIterator[AnalysisEvent]:
    """Runs the full roadmap pipeline: milestone selection -> concept
    grounding -> prerequisite mapping -> sequencing -> persistence. Every
    stage failure is emitted as a ``type="error"`` event (never raised), same
    discipline as ``run_landscape_search``.

    Owns its own DB session for the same reason ``run_landscape_search``
    does (a long-running generator driving an SSE response). Ownership of a
    ``"paper"`` target is verified again here (in addition to the router's
    own pre-flight 404 for the real HTTP path) so this function stays
    correct for any direct caller, e.g. tests -- a mismatch is treated as a
    normal mid-pipeline stage failure (an error event), not a raised 404,
    since this point is already inside the SSE stream.
    """
    yield AnalysisEvent(type="progress", stage="roadmap", message="Configuring AI provider")
    try:
        provider: AIProvider = redacting(build_provider(provider_id, api_key=api_key, endpoint=endpoint), api_key)
    except (ProviderNotFoundError, InvalidConfigError, NotImplementedError) as exc:
        logger.warning("roadmap_provider_setup_failed user_id=%s error=%s", user_id, exc)
        yield AnalysisEvent(type="error", stage="roadmap", message=str(exc))
        return

    yield AnalysisEvent(type="progress", stage="roadmap", message="Checking model availability")
    try:
        await ping_chat(provider, model)
        await ping_embed(provider, embed_model)
    except (AuthenticationError, ProviderUnavailableError, NotSupportedError, StructuredOutputError) as exc:
        logger.warning("roadmap_model_preflight_failed user_id=%s provider=%s error=%s", user_id, provider_id, exc)
        yield AnalysisEvent(type="error", stage="roadmap", message=str(exc))
        return

    async with AsyncSessionLocal() as db:
        profile = await get_or_create_profile(db, user_id)
        beginner = profile.level == "beginner"

        yield AnalysisEvent(type="progress", stage="roadmap", message="Finding milestone papers")
        try:
            if isinstance(target, RoadmapPaperTarget):
                anchor = await db.get(Paper, target.paper_id)
                if anchor is None or anchor.user_id != user_id:
                    logger.warning("roadmap_target_paper_not_owned user_id=%s paper_id=%s", user_id, target.paper_id)
                    yield AnalysisEvent(type="error", stage="roadmap", message="Target paper not found")
                    return
                target_description = anchor.title
                target_paper_id: uuid.UUID | None = anchor.id
                candidates = await select_milestone_candidates_for_paper(
                    provider,
                    anchor_title=anchor.title,
                    anchor_arxiv_id=anchor.arxiv_id,
                    beginner=beginner,
                    embed_model=embed_model,
                )
                sources = [_MilestoneSource(paper=anchor, candidate=None)] + [
                    _MilestoneSource(paper=None, candidate=candidate) for candidate in candidates
                ]
            elif isinstance(target, RoadmapTopicTarget):
                target_description = target.topic
                target_paper_id = None
                candidates = await select_milestone_candidates_for_topic(
                    provider, target.topic, beginner=beginner, embed_model=embed_model
                )
                if not candidates:
                    empty_result_error = EmptyTopicSearchResultError(
                        f"No arXiv results found for topic {target.topic!r}"
                    )
                    yield AnalysisEvent(type="error", stage="roadmap", message=empty_result_error.message)
                    return
                sources = [_MilestoneSource(paper=None, candidate=candidate) for candidate in candidates]
            else:  # pragma: no cover -- unreachable via the API's discriminated union
                raise InvalidRoadmapTargetError(f"Unknown roadmap target type: {target!r}")
        except (ArxivUnavailableError, NotSupportedError) as exc:
            logger.warning("roadmap_milestone_search_failed user_id=%s error=%s", user_id, exc)
            yield AnalysisEvent(type="error", stage="roadmap", message=str(exc))
            return

        yield AnalysisEvent(type="checkpoint", stage="roadmap", data={"milestone_candidates": len(sources)})

        yield AnalysisEvent(type="progress", stage="roadmap", message="Extracting concepts")
        try:
            milestone_drafts, all_concepts = await _build_milestone_drafts(db, provider, user_id, sources, model)
        except (StructuredOutputError, ProviderUnavailableError, AuthenticationError, NotSupportedError) as exc:
            logger.warning("roadmap_concept_extraction_failed user_id=%s error=%s", user_id, exc)
            yield AnalysisEvent(type="error", stage="roadmap", message=str(exc))
            return

        yield AnalysisEvent(type="checkpoint", stage="roadmap", data={"concepts": len(all_concepts)})

        yield AnalysisEvent(type="progress", stage="roadmap", message="Mapping prerequisites")
        try:
            edges = await propose_prerequisite_edges(provider, all_concepts, model=model)
        except (StructuredOutputError, ProviderUnavailableError, AuthenticationError, NotSupportedError) as exc:
            logger.warning("roadmap_prerequisite_mapping_failed user_id=%s error=%s", user_id, exc)
            yield AnalysisEvent(type="error", stage="roadmap", message=str(exc))
            return

        yield AnalysisEvent(type="checkpoint", stage="roadmap", data={"edges": len(edges)})

        yield AnalysisEvent(type="progress", stage="roadmap", message="Sequencing roadmap")
        depths = compute_concept_depths(all_concepts, edges)
        milestones = sequence_milestones(milestone_drafts, depths)
        try:
            overview = await generate_roadmap_overview(
                provider, milestones, all_concepts, beginner=beginner, model=model
            )
        except (StructuredOutputError, ProviderUnavailableError, AuthenticationError, NotSupportedError) as exc:
            logger.warning("roadmap_overview_generation_failed user_id=%s error=%s", user_id, exc)
            yield AnalysisEvent(type="error", stage="roadmap", message=str(exc))
            return

        roadmap = await _persist_roadmap(
            db, user_id, target_description, target_paper_id, all_concepts, edges, milestones, overview
        )
        response = RoadmapResponse.model_validate(roadmap)

    yield AnalysisEvent(type="done", stage="roadmap", data=response.model_dump(mode="json"))


async def get_owned_roadmap(db: AsyncSession, roadmap_id: uuid.UUID, user_id: uuid.UUID) -> Roadmap:
    """Fetches a roadmap only if it belongs to ``user_id`` -- same 404-not-403
    row-level authorization discipline as ``get_owned_landscape``."""
    roadmap = await db.scalar(select(Roadmap).where(Roadmap.id == roadmap_id, Roadmap.user_id == user_id))
    if roadmap is None:
        raise RoadmapNotFoundError("Roadmap not found")
    return roadmap


async def list_roadmaps(db: AsyncSession, user_id: uuid.UUID) -> list[Roadmap]:
    result = await db.scalars(select(Roadmap).where(Roadmap.user_id == user_id).order_by(Roadmap.created_at.desc()))
    return list(result.all())


def build_roadmap_summary(roadmap: Roadmap) -> RoadmapSummary:
    completed_count = sum(1 for milestone in roadmap.milestones if milestone.get("status") == "completed")
    return RoadmapSummary(
        id=roadmap.id,
        target_description=roadmap.target_description,
        created_at=roadmap.created_at,
        milestone_count=len(roadmap.milestones),
        completed_count=completed_count,
    )


async def update_milestone_status(
    db: AsyncSession, roadmap_id: uuid.UUID, user_id: uuid.UUID, milestone_id: str, status: str
) -> Roadmap:
    """Ownership-checked (via ``get_owned_roadmap``), validates ``milestone_id``
    exists in the roadmap's persisted ``milestones`` JSONB and ``status`` is
    one of the four allowed values, then persists the mutated JSONB back.

    Rebuilds the ``milestones`` list rather than mutating an entry in place
    (this project's immutability rule, and the practical reason JSONB column
    mutation needs a fresh list assigned for SQLAlchemy's change-tracking to
    pick it up).
    """
    if status not in _ALLOWED_MILESTONE_STATUSES:
        raise InvalidMilestoneStatusError(f"Invalid milestone status: {status!r}")

    roadmap = await get_owned_roadmap(db, roadmap_id, user_id)

    found = False
    updated_milestones = []
    for milestone in roadmap.milestones:
        if milestone["id"] == milestone_id:
            found = True
            updated_milestones.append({**milestone, "status": status})
        else:
            updated_milestones.append(milestone)
    if not found:
        raise MilestoneNotFoundError(f"Milestone {milestone_id!r} not found in roadmap {roadmap_id}")

    roadmap.milestones = updated_milestones
    await db.commit()
    await db.refresh(roadmap)
    return roadmap
