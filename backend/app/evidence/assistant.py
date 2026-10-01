"""Research Assistant retrieval + orchestration (docs/API_SPEC.md's ``POST
/papers/{id}/assistant``, docs/AGENTS.md's Research Assistant Agent entry).

No native tool-calling in the ``AIProvider`` interface, and none is added
here -- each of the 8 actions is implemented as (a) this module's own code
selecting the relevant claims/metrics/glossary/learning-layer content for
that action ("tool/evidence selection varies by question", AGENTS.md), then
(b) exactly one ``provider.generate()`` call grounded in exactly that
selection. Retrieval is keyword-token overlap, not embedding similarity --
semantic search needs the pgvector infrastructure Phase 5 introduces;
building it now for one feature would duplicate that future work.

Nothing here touches the database -- ``app.evidence.service.run_assistant``
loads a paper's claims/metrics/glossary/learning-layer content once and
passes them in, same "build prompt, call the provider, validate" division as
``report.py``/``technical.py``/``learning.py``.
"""

import re
import uuid
from collections.abc import Sequence
from typing import cast

from pydantic import BaseModel

from app.core.logging import get_logger
from app.evidence.exceptions import AssistantActionNotSupportedError
from app.evidence.prompts.assistant import build_assistant_prompt
from app.evidence.schemas import (
    AssistantAnswerOutput,
    AssistantClaimForPrompt,
    AssistantRetrievalContext,
    GlossaryTermForPrompt,
    LearningExcerptForPrompt,
    MetricForPrompt,
    PaperContextForPrompt,
)
from app.models.claim import ClaimKind
from app.providers.base import AIProvider

logger = get_logger(__name__)

# Broad-context actions (`understand`; `deep-dive`/`verify`/`learn` falling
# back to broad context) get every claim up to this cap rather than an
# unbounded prompt. 60 is picked as comfortably inside every supported
# provider's context window even for an unusually claims-heavy paper, while
# still being "every claim" for the large majority of real papers (Phase 2's
# extraction passes typically produce well under this many per paper).
_BROAD_CONTEXT_CLAIM_CAP = 60

# `deep-dive`/`verify` keyword-match top-k: deep-dive wants enough claims to
# support an in-depth answer, verify wants a tight, focused set around the
# one claim/number the user is skeptical of.
_DEEP_DIVE_TOP_K = 8
_VERIFY_TOP_K = 3

_CHALLENGE_CLAIM_KINDS = frozenset({ClaimKind.limitation, ClaimKind.reported_result})
_IMPLEMENT_CLAIM_KINDS = frozenset({ClaimKind.method})
_RESEARCH_CLAIM_KINDS = frozenset({ClaimKind.background})

# Kept/dropped order when `_cap_broad_context` has to cut a claim list down:
# reported-result/limitation claims are what a reader most needs to
# understand what a paper found and where it breaks, so they're kept first;
# within a kind, `verified` claims are kept before `needs-review`/
# `mismatch`/`not-found` ones, since they're the most trustworthy grounding
# for a broad-context answer.
_KIND_CENTRALITY = {
    ClaimKind.reported_result: 0,
    ClaimKind.limitation: 1,
    ClaimKind.method: 2,
    ClaimKind.background: 3,
    ClaimKind.author_interpretation: 4,
}
_STATUS_SEVERITY = {
    "verified": 0,
    "partially-matched": 1,
    "needs-review": 2,
    "mismatch": 3,
    "not-found": 4,
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "this", "that",
        "these", "those", "and", "or", "but", "if", "then", "than", "so", "of", "in", "on",
        "at", "to", "for", "with", "as", "by", "from", "about", "into", "over", "after",
        "before", "between", "out", "up", "down", "not", "no", "do", "does", "did", "doing",
        "has", "have", "had", "having", "it", "its", "what", "which", "who", "whom", "how",
        "why", "when", "where", "can", "could", "would", "should", "will", "shall", "you",
        "paper", "claim",
    }
)


class AssistantDraft(BaseModel):
    """A model's answer plus its citations, already filtered against the
    real, accessible claim set (``run_assistant_query``) -- the shape
    ``app.evidence.service.run_assistant`` turns into ``AssistantResponse``.
    """

    answer: str
    claim_ids: list[uuid.UUID]


def _tokenize(text: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) > 2 and tok not in _STOPWORDS}


def _claim_tokens(claim: AssistantClaimForPrompt) -> set[str]:
    tokens = _tokenize(claim.statement)
    for excerpt in claim.excerpts:
        tokens |= _tokenize(excerpt)
    return tokens


def _rank_by_keyword_overlap(
    question: str, claims: Sequence[AssistantClaimForPrompt]
) -> list[AssistantClaimForPrompt]:
    """Case-insensitive token-overlap score between ``question`` and each
    claim's statement + source excerpts -- design decision: semantic
    (embedding) search needs pgvector infrastructure Phase 5 introduces; a
    simple overlap score is enough for "retrieval varies by question"
    without duplicating that future work. Stable sort (ties keep claims in
    their original order) so results are deterministic for the same input.
    """
    question_tokens = _tokenize(question)
    scored = [(len(question_tokens & _claim_tokens(claim)), index, claim) for index, claim in enumerate(claims)]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [claim for _, _, claim in scored]


def _cap_broad_context(claims: Sequence[AssistantClaimForPrompt]) -> list[AssistantClaimForPrompt]:
    """Bounds a broad-context claim list at ``_BROAD_CONTEXT_CLAIM_CAP``.
    Below the cap, every claim is returned unchanged and in original order.
    Above it, the highest-centrality/highest-severity claims are kept (see
    ``_KIND_CENTRALITY``/``_STATUS_SEVERITY`` above)."""
    claim_list = list(claims)
    if len(claim_list) <= _BROAD_CONTEXT_CLAIM_CAP:
        return claim_list
    ordered = sorted(
        enumerate(claim_list),
        key=lambda pair: (
            _KIND_CENTRALITY.get(pair[1].kind, 99),
            _STATUS_SEVERITY.get(pair[1].verification_status.value, 99),
            pair[0],
        ),
    )
    return [claim for _, claim in ordered[:_BROAD_CONTEXT_CLAIM_CAP]]


def select_retrieval_context(
    action: str,
    question: str | None,
    *,
    thesis: str,
    plain_summary: str,
    research_question: str,
    claims: Sequence[AssistantClaimForPrompt],
    metrics: Sequence[MetricForPrompt],
    glossary: Sequence[GlossaryTermForPrompt],
    learning_excerpts: Sequence[LearningExcerptForPrompt],
) -> AssistantRetrievalContext:
    """The per-action retrieval heuristic (this phase's task brief). Pure
    in-memory filtering/ranking -- no DB access; the caller
    (``app.evidence.service.run_assistant``) already loaded every one of
    this paper's claims/metrics/glossary/learning-layer content once.

    Not used for ``"compare"`` -- that action's context spans multiple
    papers rather than selecting a subset of this one paper's own evidence;
    build it with ``build_paper_context`` (one call per paper) instead.
    """
    broad_context = AssistantRetrievalContext(
        thesis=thesis,
        plain_summary=plain_summary,
        research_question=research_question,
        claims=_cap_broad_context(claims),
        metrics=list(metrics),
        glossary=list(glossary),
    )

    if action == "understand":
        return broad_context
    if action == "deep-dive":
        if question:
            return AssistantRetrievalContext(claims=_rank_by_keyword_overlap(question, claims)[:_DEEP_DIVE_TOP_K])
        return broad_context
    if action == "challenge":
        relevant = [claim for claim in claims if claim.kind in _CHALLENGE_CLAIM_KINDS]
        return AssistantRetrievalContext(claims=_cap_broad_context(relevant))
    if action == "verify":
        if question:
            return AssistantRetrievalContext(claims=_rank_by_keyword_overlap(question, claims)[:_VERIFY_TOP_K])
        return broad_context
    if action == "implement":
        # Grounded Q&A only -- a real OpenCode implementation-plan handoff is
        # Phase 8 scope (docs/ROADMAP.md), not triggered by this action.
        relevant = [claim for claim in claims if claim.kind in _IMPLEMENT_CLAIM_KINDS]
        return AssistantRetrievalContext(claims=_cap_broad_context(relevant), metrics=list(metrics))
    if action == "research":
        # Scoped to THIS paper's own background/context only -- no
        # cross-paper literature graph yet (that's Phase 7, docs/ROADMAP.md).
        relevant = [claim for claim in claims if claim.kind in _RESEARCH_CLAIM_KINDS]
        return AssistantRetrievalContext(
            thesis=thesis,
            plain_summary=plain_summary,
            research_question=research_question,
            claims=_cap_broad_context(relevant),
            glossary=list(glossary),
        )
    if action == "learn":
        if learning_excerpts:
            return AssistantRetrievalContext(
                claims=_cap_broad_context(claims), learning_excerpts=list(learning_excerpts)
            )
        return broad_context
    if action == "compare":
        raise AssistantActionNotSupportedError(
            "select_retrieval_context does not handle 'compare' -- build per-paper context "
            "with build_paper_context and pass it as papers_context instead"
        )
    raise AssistantActionNotSupportedError(f"Unknown assistant action: {action!r}")


def build_paper_context(
    *,
    paper_id: uuid.UUID,
    title: str,
    thesis: str,
    plain_summary: str,
    research_question: str,
    claims: Sequence[AssistantClaimForPrompt],
) -> PaperContextForPrompt:
    """One paper's slice of the ``compare`` action's context -- same
    broad-context cap as every other action, applied per paper."""
    return PaperContextForPrompt(
        paper_id=paper_id,
        title=title,
        thesis=thesis,
        plain_summary=plain_summary,
        research_question=research_question,
        claims=_cap_broad_context(claims),
    )


async def run_assistant_query(
    provider: AIProvider,
    *,
    action: str,
    question: str | None,
    context: AssistantRetrievalContext,
    known_claim_ids: set[uuid.UUID],
    papers_context: Sequence[PaperContextForPrompt] = (),
    model: str,
) -> AssistantDraft:
    """Builds the action's prompt from exactly the retrieved ``context``,
    makes the one ``provider.generate()`` call, and filters the model's
    cited ``claim_ids`` against ``known_claim_ids`` (the paper's -- and for
    ``"compare"``, every compared paper's -- real, persisted claims).

    A cited id that doesn't resolve is dropped with a logged warning rather
    than rejecting the whole answer (design decision: this content is never
    persisted, so a live answer minus one bad citation is still useful --
    silently trusting an unresolvable citation is not). Raises
    ``app.providers.errors.StructuredOutputError`` (surfaced by
    ``provider.generate``, not swallowed here) if the model's output fails
    schema validation twice.
    """
    prompt = build_assistant_prompt(
        action=action,
        question=question,
        thesis=context.thesis,
        plain_summary=context.plain_summary,
        research_question=context.research_question,
        claims=context.claims,
        metrics=context.metrics,
        glossary=context.glossary,
        learning_excerpts=context.learning_excerpts,
        papers_context=papers_context,
    )
    opts: dict[str, object] = {"model": model}
    output = cast(AssistantAnswerOutput, await provider.generate(prompt, AssistantAnswerOutput, **opts))

    resolved_claim_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for claim_id in output.claim_ids:
        if claim_id not in known_claim_ids:
            logger.warning("assistant_answer_cited_unknown_claim_id action=%s claim_id=%s", action, claim_id)
            continue
        if claim_id not in seen:
            seen.add(claim_id)
            resolved_claim_ids.append(claim_id)

    return AssistantDraft(answer=output.answer, claim_ids=resolved_claim_ids)
