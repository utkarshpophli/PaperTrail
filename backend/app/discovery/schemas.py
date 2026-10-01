"""Pydantic v2 request/response shapes for the Discovery module (Phase 5):
Topic Landscape search, method clustering, user Profile, and personalized
recommendations. See docs/API_SPEC.md's "Discovery (Phase 5)" section and
docs/DATA_MODEL.md's ``TopicLandscape``/``MethodCluster``/``Profile`` entries.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.claim import VerificationStatus

_ShortText = Annotated[str, Field(min_length=1, max_length=200)]


# --- provider call configuration (per-request, no saved "stage assignment"
# -- ARCHITECTURE.md's Phase 5 decisions) ------------------------------------


class DiscoveryProviderConfig(BaseModel):
    provider_id: str
    api_key: str | None = None
    endpoint: str | None = None
    model: str = Field(min_length=1, max_length=200)
    embed_model: str = Field(min_length=1, max_length=200)


# --- POST /discover/landscape -----------------------------------------------


class LandscapeSearchRequest(DiscoveryProviderConfig):
    topic: Annotated[str, Field(min_length=1, max_length=300)]


# --- per-paper extraction card (extraction.py) ------------------------------


class ExtractionFieldDraft(BaseModel):
    """One field of the per-paper extraction card, as returned by the AI
    provider -- before its excerpt is checked against the paper's own
    abstract."""

    text: Annotated[str, Field(min_length=1, max_length=500)]
    # Verbatim quotation copied from the abstract -- verified by
    # app.evidence.verifier.classify_excerpt, never trusted on the model's
    # own say-so (AI_PROVIDERS.md's hallucination handling).
    excerpt: Annotated[str, Field(min_length=1, max_length=500)]


class PaperExtractionCardDraft(BaseModel):
    tldr: ExtractionFieldDraft
    problem: ExtractionFieldDraft
    method: ExtractionFieldDraft
    results: ExtractionFieldDraft
    why_it_matters: ExtractionFieldDraft


class ExtractedField(BaseModel):
    """Post-verification shape: the model's synthesized text plus the
    independent verifier's judgment on whether its supporting excerpt
    actually appears in the abstract -- set only by
    ``app.evidence.verifier.classify_excerpt``, never upgraded by anything
    else, mirroring ``Claim.verification_status``'s discipline."""

    text: str
    verification_status: VerificationStatus


class PaperExtractionCard(BaseModel):
    tldr: ExtractedField
    problem: ExtractedField
    method: ExtractedField
    results: ExtractedField
    why_it_matters: ExtractedField


# --- clustering (clustering.py) --------------------------------------------


class ClusterAssignmentDraft(BaseModel):
    label: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(min_length=1, max_length=800)]
    arxiv_ids: list[str] = Field(min_length=1)


class LandscapeClusteringOutput(BaseModel):
    """LLM structured output for the clustering pass. Cluster count (2-5) is
    a hard schema constraint, enforced via the existing retry-once
    structured-output path (``app.providers.structured_output``) -- not just
    a prompt instruction."""

    overview: Annotated[str, Field(min_length=1, max_length=4000)]
    clusters: list[ClusterAssignmentDraft] = Field(min_length=2, max_length=5)


# --- persisted landscape shape (TopicLandscape.papers / .clusters JSONB) ---


class LandscapePaperItem(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    year: int | None
    pdf_url: str
    abstract: str
    relevance_score: float
    cluster_id: str | None = None
    extraction: PaperExtractionCard | None = None


class MethodClusterItem(BaseModel):
    id: str
    label: str
    description: str
    paper_ids: list[str]


class TopicLandscapeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    topic: str
    overview: str
    papers: list[LandscapePaperItem]
    clusters: list[MethodClusterItem]
    created_at: datetime


# --- GET /discover/landscape/{id}/graph -- exact frontend contract, do not
# deviate (docs/ARCHITECTURE.md's Phase 5 decisions: the Neural Map's generic
# {nodes, edges} shape, shared with Phase 7's Literature Graph). ------------


class GraphNode(BaseModel):
    id: str
    label: str
    color: str
    size: float | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: Literal["semantically_similar"] = "semantically_similar"
    weight: float | None = None


class LandscapeGraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# --- profile -----------------------------------------------------------

ProfileLevel = Literal["beginner", "intermediate", "advanced"]


class ProfileUpdateRequest(BaseModel):
    interests: list[_ShortText] = Field(default_factory=list, max_length=20)
    level: ProfileLevel = "beginner"
    goals: list[_ShortText] = Field(default_factory=list, max_length=20)


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    interests: list[str]
    level: str
    goals: list[str]
    created_at: datetime
    updated_at: datetime


# --- GET /discover/recommendations -----------------------------------------


class RecommendationItem(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    year: int | None
    abstract: str
    relevance_score: float
    # Always grounded in the specific profile signal (interest/goal string)
    # that drove the match -- never a generic "you might like this"
    # (recommendation-engineer's quality bar).
    explanation: str


# --- Phase 6: roadmap / prerequisite graph ----------------------------------
#
# See ARCHITECTURE.md's "Phase 6 decisions": a Concept is never free-floating
# LLM output -- every one traces to a real GlossaryTerm row (owned, analyzed
# paper) or a verified excerpt from an un-ingested candidate's own abstract
# (app.discovery.concepts). PrerequisiteEdges are only ever drawn between
# Concepts in that grounded set (app.discovery.prerequisites).


class ConceptTermDraft(BaseModel):
    """One LLM-proposed concept for an un-ingested arXiv candidate, before its
    ``excerpt`` is checked against the paper's own abstract
    (``app.evidence.verifier.classify_excerpt``)."""

    term: Annotated[str, Field(min_length=1, max_length=200)]
    definition: Annotated[str, Field(min_length=1, max_length=1000)]
    # Verbatim quotation copied from the abstract -- never trusted on the
    # model's own say-so, same discipline as ExtractionFieldDraft.excerpt.
    excerpt: Annotated[str, Field(min_length=1, max_length=500)]


class ConceptExtractionOutput(BaseModel):
    """Structured output for one un-ingested candidate's concept-extraction
    pass. 3-6 is a schema constraint (retry-once on validation failure), same
    discipline as ``LandscapeClusteringOutput``'s cluster count."""

    concepts: list[ConceptTermDraft] = Field(min_length=3, max_length=6)


class Concept(BaseModel):
    """A grounded prerequisite-graph node -- persisted verbatim into
    ``Roadmap.concepts`` JSONB. Exactly one of ``source_paper_id``/
    ``source_arxiv_id`` is set, mirroring which grounding path produced it."""

    id: str
    name: str
    description: str
    source_paper_id: uuid.UUID | None = None
    source_arxiv_id: str | None = None
    grounding_excerpt: str
    verification_status: VerificationStatus


class PrerequisiteEdgeDraft(BaseModel):
    concept_id: str
    prerequisite_concept_id: str


class PrerequisiteExtractionOutput(BaseModel):
    """Structured output for the prerequisite-proposal pass. No min/max count
    constraint (unlike clustering/concepts) -- zero proposed edges is a valid
    outcome for a small/flat concept set, not a schema failure."""

    edges: list[PrerequisiteEdgeDraft] = Field(default_factory=list, max_length=200)


class PrerequisiteEdge(BaseModel):
    """A prerequisite-graph edge -- persisted verbatim into ``Roadmap.edges``
    JSONB. Only ever constructed after both ids are checked against the
    grounded concept set (app.discovery.prerequisites.propose_prerequisite_edges)."""

    concept_id: str
    prerequisite_concept_id: str


class RoadmapOverviewOutput(BaseModel):
    overview: Annotated[str, Field(min_length=1, max_length=4000)]


MilestoneStatus = Literal["locked", "available", "completed", "skipped"]


class Milestone(BaseModel):
    id: str
    order: int
    paper_id: uuid.UUID | None = None
    arxiv_id: str | None = None
    title: str
    concept_ids: list[str]
    status: MilestoneStatus


# --- POST /discover/roadmap -- tagged-union target (Pydantic discriminated
# union: a body with a missing/invalid `type`, or missing the field that
# `type` requires, is a plain 422 -- no manual validator needed). ------------


class RoadmapPaperTarget(BaseModel):
    type: Literal["paper"]
    paper_id: uuid.UUID


class RoadmapTopicTarget(BaseModel):
    type: Literal["topic"]
    topic: Annotated[str, Field(min_length=1, max_length=300)]


RoadmapTarget = Annotated[RoadmapPaperTarget | RoadmapTopicTarget, Field(discriminator="type")]


class RoadmapCreateRequest(DiscoveryProviderConfig):
    target: RoadmapTarget


class RoadmapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_description: str
    target_paper_id: uuid.UUID | None
    concepts: list[Concept]
    edges: list[PrerequisiteEdge]
    milestones: list[Milestone]
    overview: str
    created_at: datetime
    updated_at: datetime


class RoadmapSummary(BaseModel):
    id: uuid.UUID
    target_description: str
    created_at: datetime
    milestone_count: int
    completed_count: int


# --- PATCH /discover/roadmap/{id}/milestones/{milestone_id} ----------------
# "locked" deliberately excluded: it's the system-assigned initial state for
# every milestone but the first, never something a user sets manually
# (PRD.md's "follow/skip/mark known manually" journey has no "re-lock" step).


class MilestoneUpdateRequest(BaseModel):
    status: Literal["completed", "skipped", "available"]


# --- Phase 7: POST /discover/landscape/{id}/promote -------------------------
# Wires the route Phase 5 deferred (no Collection model existed yet). See
# ARCHITECTURE.md's Phase 7 decisions: only already-ingested, owned papers
# (matched by arxiv_id) are added to the target Collection -- a landscape
# candidate the user hasn't ingested is reported back as skipped, never
# turned into a bare arxiv_id string inside Collection.paper_ids.


class LandscapePromoteRequest(BaseModel):
    collection_id: uuid.UUID | None = None
    collection_name: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class LandscapePromoteResponse(BaseModel):
    collection_id: uuid.UUID
    added: list[str]  # arxiv_ids of landscape papers added to the collection
    skipped_not_ingested: list[str]  # arxiv_ids not yet ingested as an owned Paper
