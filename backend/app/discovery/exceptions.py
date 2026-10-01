"""Typed exceptions for the discovery domain -- never a bare ``Exception``,
each maps to the API error envelope (API_SPEC.md Conventions)."""

from app.core.errors import AppError


class TopicLandscapeNotFoundError(AppError):
    """Raised by ``get_owned_landscape`` when no landscape with the given id
    exists, or it exists but belongs to a different user -- both cases look
    identical to the caller (SECURITY.md row-level authorization: never leak
    existence of another user's data via a 403 vs 404 split)."""

    status_code = 404
    code = "topic_landscape_not_found"


class EmptyTopicSearchResultError(AppError):
    """Raised internally when ``search_arxiv_topic`` returns zero candidates
    for a topic -- caught by the landscape pipeline and surfaced as a
    ``type="error"`` SSE event (same treatment as any other mid-pipeline
    stage failure), not a 4xx raised before the stream starts, since arXiv
    querying happens after the SSE stream has already begun emitting
    progress events."""

    status_code = 404
    code = "empty_topic_search_result"


class InvalidPromoteTargetError(AppError):
    """Raised by ``promote_landscape`` when neither ``collection_id`` nor
    ``collection_name`` is supplied -- there's no target to add papers to."""

    status_code = 422
    code = "invalid_promote_target"


class ClusterReferencesUnknownPaperError(AppError):
    """A generated cluster assignment emitted an ``arxiv_id`` that isn't one
    of the ranked candidate papers actually passed to the clustering prompt.
    Raised before any cluster is persisted -- same reject-the-whole-batch
    discipline as ``app.evidence.exceptions.SectionReferencesUnknownClaimError``."""

    status_code = 422
    code = "cluster_references_unknown_paper"


# --- Phase 6: roadmap / prerequisite graph ----------------------------------


class RoadmapNotFoundError(AppError):
    """Raised by ``get_owned_roadmap`` when no roadmap with the given id
    exists, or it exists but belongs to a different user -- same
    non-leaking 404-not-403 discipline as ``TopicLandscapeNotFoundError``."""

    status_code = 404
    code = "roadmap_not_found"


class MilestoneNotFoundError(AppError):
    """Raised by ``update_milestone_status`` when ``milestone_id`` doesn't
    match any entry in the roadmap's persisted ``milestones`` JSONB."""

    status_code = 404
    code = "milestone_not_found"


class InvalidMilestoneStatusError(AppError):
    """Defensive guard in ``update_milestone_status`` for a status value
    outside the four allowed values. In practice unreachable through the
    ``PATCH`` route (``MilestoneUpdateRequest.status``'s ``Literal`` already
    rejects anything else with a 422) -- kept for any non-HTTP call site."""

    status_code = 422
    code = "invalid_milestone_status"


class InvalidRoadmapTargetError(AppError):
    """Defensive guard for a ``RoadmapTarget.type`` outside the discriminated
    union's known literals. In practice unreachable through the API (the
    request schema's discriminated union already rejects this at validation
    time with a 422) -- kept as a typed error for any non-HTTP call site of
    ``app.discovery.service.run_roadmap_generation``, rather than an
    unguarded ``KeyError``/``AttributeError`` on an unexpected target shape.
    """

    status_code = 422
    code = "invalid_roadmap_target"
