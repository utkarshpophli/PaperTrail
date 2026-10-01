"""Unit tests for the visual-stage derivation modules (app.evidence.story /
app.evidence.learning). Fake provider (TESTING.md: mock the external AI
boundary, not our own code) -- covers successful claim_id-validated
generation and rejection of a fabricated claim_id for all five content
types, plus sanitization of a script-injection payload in a quiz explanation
and a derivation step explanation (this phase's task brief).
"""

import uuid

import pytest

from app.evidence.exceptions import (
    StoryIntegrityError,
    DerivationReferencesUnknownClaimError,
    QuizReferencesUnknownClaimError,
    SectionReferencesUnknownClaimError,
)
from app.evidence.learning import (
    generate_application_guide_sections,
    generate_derivations,
    generate_primer_sections,
    generate_quiz_questions,
)
from app.evidence.schemas import (
    DerivationDraft,
    DerivationsOutput,
    DerivationStepDraft,
    GeneratedSectionDraft,
    ClaimForPrompt,
    GeneratedSectionsOutput,
    MetricForPrompt,
    QuizQuestionDraft,
    QuizQuestionsOutput,
)
from app.evidence.story import generate_story
from app.evidence.story_visuals import StorySpecOutput
from app.models.claim import ClaimKind
from tests.evidence.fake_provider import FakeProvider
from tests.evidence.story_fixtures import make_story
from tests.evidence.test_derivation import _CLAIM_1, _CLAIM_2


async def test_generate_story_returns_validated_spec() -> None:
    method = _CLAIM_1  # method; excerpt "a new attention mechanism"
    limitation = ClaimForPrompt(
        id=uuid.uuid4(), kind=ClaimKind.limitation, statement="Needs compute.", excerpts=["needs a lot of compute"]
    )
    output = make_story(method_id=method.id, limitation_id=limitation.id)
    provider = FakeProvider({StorySpecOutput: output})
    metrics = [MetricForPrompt(label="Gain", value="10", display_value="10%")]

    story = await generate_story(
        provider,
        thesis="T",
        plain_summary="S",
        research_question="Q",
        claims=[method, limitation],
        metrics=metrics,
        model="m",
    )

    assert story == output
    prompt, schema = provider.calls[0]
    assert schema is StorySpecOutput
    assert f"[CLAIM {method.id}] (kind=method" in prompt


async def test_generate_story_rejects_unknown_claim_id_after_one_retry() -> None:
    method = _CLAIM_1
    output = make_story(method_id=uuid.uuid4(), limitation_id=uuid.uuid4())
    provider = FakeProvider({StorySpecOutput: output})

    with pytest.raises(StoryIntegrityError, match="unknown claim_id"):
        await generate_story(
            provider, thesis="T", plain_summary="S", research_question="Q", claims=[method], metrics=[], model="m"
        )

    assert len(provider.calls) == 2  # exactly one retry, carrying the violations as feedback
    assert "unknown claim_id" in provider.calls[1][0]


async def test_generate_primer_sections_returns_validated_drafts() -> None:
    background_claim = _CLAIM_2  # reported_result -- filtering exercised separately below
    output = GeneratedSectionsOutput(
        sections=[GeneratedSectionDraft(heading="Background", body="Context.", claim_ids=[_CLAIM_1.id])]
    )
    provider = FakeProvider({GeneratedSectionsOutput: output})

    sections = await generate_primer_sections(provider, claims=[_CLAIM_1, background_claim], model="m")

    assert sections == output.sections


async def test_generate_primer_sections_rejects_unknown_claim_id() -> None:
    fabricated_id = uuid.uuid4()
    output = GeneratedSectionsOutput(
        sections=[GeneratedSectionDraft(heading="Background", body="Body.", claim_ids=[fabricated_id])]
    )
    provider = FakeProvider({GeneratedSectionsOutput: output})

    with pytest.raises(SectionReferencesUnknownClaimError):
        await generate_primer_sections(provider, claims=[_CLAIM_1], model="m")


async def test_generate_application_guide_sections_returns_validated_drafts() -> None:
    output = GeneratedSectionsOutput(
        sections=[GeneratedSectionDraft(heading="Usage", body="How to apply it.", claim_ids=[_CLAIM_1.id])]
    )
    provider = FakeProvider({GeneratedSectionsOutput: output})
    metrics = [MetricForPrompt(label="BLEU", value="2", display_value="+2")]

    sections = await generate_application_guide_sections(provider, claims=[_CLAIM_1, _CLAIM_2], metrics=metrics, model="m")

    assert sections == output.sections


async def test_generate_application_guide_sections_rejects_unknown_claim_id() -> None:
    fabricated_id = uuid.uuid4()
    output = GeneratedSectionsOutput(
        sections=[GeneratedSectionDraft(heading="Usage", body="Body.", claim_ids=[fabricated_id])]
    )
    provider = FakeProvider({GeneratedSectionsOutput: output})

    with pytest.raises(SectionReferencesUnknownClaimError):
        await generate_application_guide_sections(provider, claims=[_CLAIM_1], metrics=[], model="m")


async def test_generate_quiz_questions_returns_validated_drafts() -> None:
    output = QuizQuestionsOutput(
        questions=[
            QuizQuestionDraft(
                question="What mechanism does the method use?",
                options=["Attention", "Convolution"],
                correct_answer="Attention",
                explanation="The paper describes a new attention mechanism.",
                claim_ids=[_CLAIM_1.id],
            )
        ]
    )
    provider = FakeProvider({QuizQuestionsOutput: output})

    questions = await generate_quiz_questions(provider, claims=[_CLAIM_1, _CLAIM_2], model="m")

    assert questions == output.questions


async def test_generate_quiz_questions_rejects_unknown_claim_id() -> None:
    fabricated_id = uuid.uuid4()
    output = QuizQuestionsOutput(
        questions=[
            QuizQuestionDraft(
                question="Q?", correct_answer="A", explanation="E", claim_ids=[fabricated_id]
            )
        ]
    )
    provider = FakeProvider({QuizQuestionsOutput: output})

    with pytest.raises(QuizReferencesUnknownClaimError):
        await generate_quiz_questions(provider, claims=[_CLAIM_1], model="m")


async def test_generate_derivations_returns_validated_drafts() -> None:
    output = DerivationsOutput(
        derivations=[
            DerivationDraft(
                title="Attention score",
                steps=[
                    DerivationStepDraft(
                        explanation="Compute the score.", formula="score = QK^T", claim_ids=[_CLAIM_1.id]
                    )
                ],
            )
        ]
    )
    provider = FakeProvider({DerivationsOutput: output})
    metrics = [MetricForPrompt(label="BLEU", value="2", display_value="+2")]

    derivations = await generate_derivations(provider, claims=[_CLAIM_1, _CLAIM_2], metrics=metrics, model="m")

    assert derivations == output.derivations


async def test_generate_derivations_rejects_unknown_claim_id() -> None:
    fabricated_id = uuid.uuid4()
    output = DerivationsOutput(
        derivations=[
            DerivationDraft(
                title="Attention score",
                steps=[DerivationStepDraft(explanation="E", formula="F", claim_ids=[fabricated_id])],
            )
        ]
    )
    provider = FakeProvider({DerivationsOutput: output})

    with pytest.raises(DerivationReferencesUnknownClaimError):
        await generate_derivations(provider, claims=[_CLAIM_1], metrics=[], model="m")


async def test_generate_application_guide_filters_prompt_to_relevant_claim_kinds() -> None:
    """method/reported-result feed the prompt; a limitation claim does not --
    but claim_id validation still checks against the full claim set passed
    in, not just the filtered prompt subset (learning.py's module docstring),
    same rule technical.py already documents."""
    limitation_claim = _make_claim(ClaimKind.limitation, "Requires large compute.")
    output = GeneratedSectionsOutput(
        sections=[GeneratedSectionDraft(heading="Usage", body="Body.", claim_ids=[_CLAIM_1.id])]
    )
    provider = FakeProvider({GeneratedSectionsOutput: output})

    await generate_application_guide_sections(provider, claims=[_CLAIM_1, limitation_claim], metrics=[], model="m")

    prompt, _ = provider.calls[0]
    assert f"[CLAIM {_CLAIM_1.id}]" in prompt
    assert f"[CLAIM {limitation_claim.id}]" not in prompt


def _make_claim(kind: ClaimKind, statement: str):
    return ClaimForPrompt(id=uuid.uuid4(), kind=kind, statement=statement, excerpts=[statement])


# ---- over-length draft fields (security review MEDIUM) --------------------
# Regression: heading/correct_answer/title must be rejected at the Pydantic
# schema boundary (triggering the existing one-retry-then-surface path) if
# they exceed their DB column's actual width -- not reach persistence and
# crash with a raw Postgres DataError. Each column width is asserted against
# directly so a future migration changing the column silently invalidates
# this test instead of the two constants quietly drifting apart.


def test_generated_section_draft_rejects_heading_longer_than_title_column() -> None:
    from app.models.generated_section import GeneratedSection

    column_width = GeneratedSection.__table__.c.title.type.length
    with pytest.raises(ValueError):
        GeneratedSectionDraft(heading="x" * (column_width + 1), body="Body.", claim_ids=[_CLAIM_1.id])
    # Exactly at the limit must still succeed.
    GeneratedSectionDraft(heading="x" * column_width, body="Body.", claim_ids=[_CLAIM_1.id])


def test_quiz_question_draft_rejects_correct_answer_longer_than_column() -> None:
    from app.models.learning_quiz_question import LearningQuizQuestion

    column_width = LearningQuizQuestion.__table__.c.correct_answer.type.length
    with pytest.raises(ValueError):
        QuizQuestionDraft(
            question="Q?", correct_answer="x" * (column_width + 1), explanation="E.", claim_ids=[_CLAIM_1.id]
        )
    QuizQuestionDraft(question="Q?", correct_answer="x" * column_width, explanation="E.", claim_ids=[_CLAIM_1.id])


def test_derivation_draft_rejects_title_longer_than_column() -> None:
    from app.models.learning_derivation import LearningDerivation

    column_width = LearningDerivation.__table__.c.title.type.length
    step = DerivationStepDraft(explanation="E.", formula="x = y", claim_ids=[_CLAIM_1.id])
    with pytest.raises(ValueError):
        DerivationDraft(title="x" * (column_width + 1), steps=[step])
    DerivationDraft(title="x" * column_width, steps=[step])


def test_interactive_draft_formula_max_length_matches_grammar_and_column_width() -> None:
    from app.evidence.formula import MAX_FORMULA_LENGTH
    from app.evidence.schemas import InteractiveDraft, InteractiveParameterDraft
    from app.models.learning_interactive import LearningInteractive

    assert LearningInteractive.__table__.c.formula.type.length == MAX_FORMULA_LENGTH

    param = InteractiveParameterDraft(name="x", label="X", min=0.0, max=10.0, step=1.0, default=5.0)
    with pytest.raises(ValueError):
        InteractiveDraft(
            title="T",
            description="D",
            parameters=[param],
            formula="x" + "+1" * MAX_FORMULA_LENGTH,
            output_label="Result",
            claim_ids=[_CLAIM_1.id],
        )


def test_interactive_parameter_draft_rejects_invalid_bounds() -> None:
    from app.evidence.schemas import InteractiveParameterDraft

    with pytest.raises(ValueError):
        InteractiveParameterDraft(name="x", label="X", min=10.0, max=1.0, step=1.0, default=5.0)
    with pytest.raises(ValueError):
        InteractiveParameterDraft(name="x", label="X", min=0.0, max=10.0, step=1.0, default=20.0)
    with pytest.raises(ValueError):
        InteractiveParameterDraft(name="x", label="X", min=0.0, max=10.0, step=0.0, default=5.0)
