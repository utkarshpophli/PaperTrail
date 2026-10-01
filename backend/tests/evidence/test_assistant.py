"""Unit tests for the Research Assistant's retrieval selection and
provider-orchestration (app.evidence.assistant) -- FakeProvider (TESTING.md:
mock the external AI boundary, not our own code).

Covers: the per-action retrieval heuristic for all 8 actions, the
broad-context cap, keyword-overlap ranking, `compare`'s multi-paper
per-paper context assembly, `verify`'s keyword-matching behavior including a
claim whose verification_status is "mismatch" (the grounding data must
surface it plainly, never soften/omit it), and the claim_id-filtering
behavior (a fabricated id is dropped with a logged warning, a real one is
kept, no exception raised).
"""

import logging
import uuid

import pytest

from app.evidence.assistant import (
    _cap_broad_context,
    _rank_by_keyword_overlap,
    build_paper_context,
    run_assistant_query,
    select_retrieval_context,
)
from app.evidence.exceptions import AssistantActionNotSupportedError
from app.evidence.prompts.assistant import build_assistant_prompt
from app.evidence.schemas import (
    AssistantAnswerOutput,
    AssistantClaimForPrompt,
    AssistantRetrievalContext,
    GlossaryTermForPrompt,
    LearningExcerptForPrompt,
    MetricForPrompt,
)
from app.models.claim import ClaimKind, VerificationStatus
from tests.evidence.fake_provider import FakeProvider


def _claim(
    kind: ClaimKind,
    statement: str,
    excerpts: list[str] | None = None,
    verification_status: VerificationStatus = VerificationStatus.verified,
) -> AssistantClaimForPrompt:
    return AssistantClaimForPrompt(
        id=uuid.uuid4(),
        kind=kind,
        statement=statement,
        excerpts=excerpts or [statement],
        verification_status=verification_status,
    )


_METHOD_CLAIM = _claim(ClaimKind.method, "Uses a novel attention mechanism for translation.")
_RESULT_CLAIM = _claim(ClaimKind.reported_result, "Improves BLEU score by 10 points on WMT14.")
_LIMITATION_CLAIM = _claim(ClaimKind.limitation, "Requires very large compute budgets to train.")
_BACKGROUND_CLAIM = _claim(ClaimKind.background, "Prior work relied on recurrent architectures.")
_AUTHOR_CLAIM = _claim(ClaimKind.author_interpretation, "The authors argue attention generalizes better.")

_ALL_CLAIMS = [_METHOD_CLAIM, _RESULT_CLAIM, _LIMITATION_CLAIM, _BACKGROUND_CLAIM, _AUTHOR_CLAIM]


def _base_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = dict(
        thesis="T",
        plain_summary="S",
        research_question="Q",
        claims=_ALL_CLAIMS,
        metrics=[],
        glossary=[],
        learning_excerpts=[],
    )
    kwargs.update(overrides)
    return kwargs


# --- per-action retrieval selection ------------------------------------------


def test_understand_includes_all_claims_metrics_and_glossary() -> None:
    metrics = [MetricForPrompt(label="BLEU", value="10", display_value="+10")]
    glossary = [GlossaryTermForPrompt(term="Attention", definition="A weighting mechanism.")]

    context = select_retrieval_context("understand", None, **_base_kwargs(metrics=metrics, glossary=glossary))

    assert {c.id for c in context.claims} == {c.id for c in _ALL_CLAIMS}
    assert context.metrics == metrics
    assert context.glossary == glossary
    assert context.thesis == "T"


def test_deep_dive_with_question_ranks_by_keyword_overlap() -> None:
    context = select_retrieval_context(
        "deep-dive", "How does the attention mechanism improve translation?", **_base_kwargs()
    )

    assert context.claims[0].id == _METHOD_CLAIM.id
    assert context.thesis is None  # question-driven retrieval, no broad narrative


def test_deep_dive_without_question_falls_back_to_broad_context() -> None:
    context = select_retrieval_context("deep-dive", None, **_base_kwargs())

    assert {c.id for c in context.claims} == {c.id for c in _ALL_CLAIMS}
    assert context.thesis == "T"


def test_challenge_only_includes_limitation_and_result_claims() -> None:
    context = select_retrieval_context("challenge", None, **_base_kwargs())

    assert {c.kind for c in context.claims} == {ClaimKind.limitation, ClaimKind.reported_result}
    assert context.thesis is None


def test_verify_ranks_best_matching_claim_first_and_never_softens_mismatch() -> None:
    mismatched = _claim(
        ClaimKind.reported_result,
        "The model improves accuracy by 50 percent on the benchmark.",
        verification_status=VerificationStatus.mismatch,
    )
    question = "Is it true the model improves accuracy by 50 percent on the benchmark, as claimed?"

    context = select_retrieval_context("verify", question, **_base_kwargs(claims=[*_ALL_CLAIMS, mismatched]))

    assert context.claims[0].id == mismatched.id
    assert context.claims[0].verification_status == VerificationStatus.mismatch

    # The grounding data actually sent to the model states the mismatch
    # plainly -- nothing in the retrieval/prompt pipeline softens or omits it.
    prompt = build_assistant_prompt(action="verify", question=question, claims=context.claims)
    assert f"[CLAIM {mismatched.id}] (kind=reported-result, verification_status=mismatch)" in prompt


def test_verify_without_question_falls_back_to_broad_context() -> None:
    context = select_retrieval_context("verify", None, **_base_kwargs())

    assert context.thesis == "T"
    assert {c.id for c in context.claims} == {c.id for c in _ALL_CLAIMS}


def test_implement_only_includes_method_claims_and_all_metrics() -> None:
    metrics = [MetricForPrompt(label="BLEU", value="10", display_value="+10")]

    context = select_retrieval_context("implement", None, **_base_kwargs(metrics=metrics))

    assert [c.id for c in context.claims] == [_METHOD_CLAIM.id]
    assert context.metrics == metrics
    assert context.thesis is None


def test_research_only_includes_background_claims_plus_glossary_and_narrative() -> None:
    glossary = [GlossaryTermForPrompt(term="Attention", definition="A weighting mechanism.")]

    context = select_retrieval_context("research", None, **_base_kwargs(glossary=glossary))

    assert [c.id for c in context.claims] == [_BACKGROUND_CLAIM.id]
    assert context.glossary == glossary
    assert context.thesis == "T"


def test_learn_grounds_in_learning_layer_when_it_exists() -> None:
    excerpts = [LearningExcerptForPrompt(heading="Primer", body="An intro to attention.")]

    context = select_retrieval_context("learn", None, **_base_kwargs(learning_excerpts=excerpts))

    assert context.learning_excerpts == excerpts
    assert context.thesis is None


def test_learn_falls_back_to_broad_context_when_no_learning_layer_exists() -> None:
    context = select_retrieval_context("learn", None, **_base_kwargs(learning_excerpts=[]))

    assert context.thesis == "T"
    assert {c.id for c in context.claims} == {c.id for c in _ALL_CLAIMS}


def test_compare_is_rejected_by_select_retrieval_context() -> None:
    """`compare` spans multiple papers -- its context is built with
    `build_paper_context`, one call per paper, never through this
    single-paper dispatcher."""
    with pytest.raises(AssistantActionNotSupportedError):
        select_retrieval_context("compare", None, **_base_kwargs())


def test_unknown_action_raises() -> None:
    with pytest.raises(AssistantActionNotSupportedError):
        select_retrieval_context("nonsense", None, **_base_kwargs())


# --- broad-context cap -------------------------------------------------------


def test_cap_broad_context_keeps_result_and_limitation_claims_over_background_when_over_cap() -> None:
    many_background = [_claim(ClaimKind.background, f"Background fact {i}.") for i in range(70)]
    claims = [_RESULT_CLAIM, _LIMITATION_CLAIM, *many_background]

    capped = _cap_broad_context(claims)

    assert len(capped) == 60
    assert _RESULT_CLAIM in capped
    assert _LIMITATION_CLAIM in capped


def test_cap_broad_context_is_a_no_op_under_the_cap() -> None:
    assert _cap_broad_context(_ALL_CLAIMS) == _ALL_CLAIMS


# --- keyword-overlap ranking --------------------------------------------------


def test_rank_by_keyword_overlap_orders_most_relevant_claim_first() -> None:
    ranked = _rank_by_keyword_overlap("What about the attention mechanism for translation?", _ALL_CLAIMS)

    assert ranked[0].id == _METHOD_CLAIM.id


def test_rank_by_keyword_overlap_is_stable_when_nothing_matches() -> None:
    ranked = _rank_by_keyword_overlap("completely unrelated question xyz", _ALL_CLAIMS)

    assert [c.id for c in ranked] == [c.id for c in _ALL_CLAIMS]


# --- compare's per-paper context assembly ------------------------------------


def test_build_paper_context_caps_claims_per_paper() -> None:
    many_claims = [_claim(ClaimKind.background, f"Fact {i}.") for i in range(70)]

    context = build_paper_context(
        paper_id=uuid.uuid4(),
        title="Other Paper",
        thesis="T2",
        plain_summary="S2",
        research_question="Q2",
        claims=many_claims,
    )

    assert len(context.claims) == 60
    assert context.title == "Other Paper"


async def test_run_assistant_query_builds_compare_prompt_from_papers_context() -> None:
    other_paper_id = uuid.uuid4()
    other_claim = _claim(ClaimKind.reported_result, "The baseline paper improves accuracy by 5%.")
    papers_context = [
        build_paper_context(
            paper_id=uuid.uuid4(),
            title="Primary Paper",
            thesis="T",
            plain_summary="S",
            research_question="Q",
            claims=[_RESULT_CLAIM],
        ),
        build_paper_context(
            paper_id=other_paper_id,
            title="Other Paper",
            thesis="T2",
            plain_summary="S2",
            research_question="Q2",
            claims=[other_claim],
        ),
    ]
    output = AssistantAnswerOutput(answer="Comparison.", claim_ids=[_RESULT_CLAIM.id, other_claim.id])
    provider = FakeProvider({AssistantAnswerOutput: output})

    draft = await run_assistant_query(
        provider,
        action="compare",
        question=None,
        context=AssistantRetrievalContext(),
        known_claim_ids={_RESULT_CLAIM.id, other_claim.id},
        papers_context=papers_context,
        model="m",
    )

    prompt, schema = provider.calls[0]
    assert schema is AssistantAnswerOutput
    assert f"[PAPER {other_paper_id} - Other Paper]" in prompt
    assert draft.claim_ids == [_RESULT_CLAIM.id, other_claim.id]


# --- run_assistant_query: claim_id filtering ---------------------------------


async def test_run_assistant_query_drops_fabricated_claim_id_keeps_real_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    real_id = _METHOD_CLAIM.id
    fabricated_id = uuid.uuid4()
    output = AssistantAnswerOutput(answer="Grounded answer.", claim_ids=[real_id, fabricated_id])
    provider = FakeProvider({AssistantAnswerOutput: output})

    # app.core.logging.get_logger sets propagate=False (avoids double-logging
    # via the root logger in production), so caplog -- which only listens on
    # the root logger by default -- needs its handler attached directly to
    # this named logger to observe records from it.
    target_logger = logging.getLogger("app.evidence.assistant")
    target_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="app.evidence.assistant"):
            draft = await run_assistant_query(
                provider,
                action="understand",
                question=None,
                context=AssistantRetrievalContext(claims=[_METHOD_CLAIM]),
                known_claim_ids={real_id},
                model="m",
            )
    finally:
        target_logger.removeHandler(caplog.handler)

    assert draft.answer == "Grounded answer."
    assert draft.claim_ids == [real_id]
    assert any("assistant_answer_cited_unknown_claim_id" in record.getMessage() for record in caplog.records)


async def test_run_assistant_query_dedupes_repeated_claim_ids() -> None:
    real_id = _METHOD_CLAIM.id
    output = AssistantAnswerOutput(answer="Answer.", claim_ids=[real_id, real_id])
    provider = FakeProvider({AssistantAnswerOutput: output})

    draft = await run_assistant_query(
        provider,
        action="understand",
        question=None,
        context=AssistantRetrievalContext(claims=[_METHOD_CLAIM]),
        known_claim_ids={real_id},
        model="m",
    )

    assert draft.claim_ids == [real_id]
