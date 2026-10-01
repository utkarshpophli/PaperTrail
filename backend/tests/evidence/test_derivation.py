"""Unit tests for the report/technical derivation modules
(app.evidence.report / app.evidence.technical). Fake provider (TESTING.md:
mock the external AI boundary, not our own code) -- covers successful
claim_id-validated section generation, and the explicit "a section that
cites a fabricated claim_id gets rejected and nothing is returned for the
caller to persist" case this phase's task brief calls out.
"""

import uuid

import pytest

from app.evidence.exceptions import SectionReferencesUnknownClaimError
from app.evidence.report import generate_report_sections
from app.evidence.schemas import ClaimForPrompt, GeneratedSectionDraft, GeneratedSectionsOutput, MetricForPrompt
from app.evidence.technical import generate_technical_sections
from app.models.claim import ClaimKind
from tests.evidence.fake_provider import FakeProvider

_CLAIM_1 = ClaimForPrompt(
    id=uuid.uuid4(),
    kind=ClaimKind.method,
    statement="Uses a new attention mechanism.",
    excerpts=["a new attention mechanism"],
)
_CLAIM_2 = ClaimForPrompt(
    id=uuid.uuid4(),
    kind=ClaimKind.reported_result,
    statement="Improves BLEU by 2 points.",
    excerpts=["improves BLEU by 2 points"],
)


async def test_generate_report_sections_returns_validated_drafts() -> None:
    output = GeneratedSectionsOutput(
        sections=[
            GeneratedSectionDraft(heading="Overview", body="Synthesized overview.", claim_ids=[_CLAIM_1.id, _CLAIM_2.id])
        ]
    )
    provider = FakeProvider({GeneratedSectionsOutput: output})

    sections = await generate_report_sections(
        provider, thesis="T", plain_summary="S", research_question="Q", claims=[_CLAIM_1, _CLAIM_2], model="m"
    )

    assert sections == output.sections


async def test_generate_report_sections_rejects_unknown_claim_id() -> None:
    fabricated_id = uuid.uuid4()
    output = GeneratedSectionsOutput(sections=[GeneratedSectionDraft(heading="Overview", body="Body.", claim_ids=[fabricated_id])])
    provider = FakeProvider({GeneratedSectionsOutput: output})

    with pytest.raises(SectionReferencesUnknownClaimError):
        await generate_report_sections(provider, thesis="T", plain_summary="S", research_question="Q", claims=[_CLAIM_1], model="m")


async def test_generate_technical_sections_returns_validated_drafts() -> None:
    output = GeneratedSectionsOutput(sections=[GeneratedSectionDraft(heading="Method", body="Details.", claim_ids=[_CLAIM_1.id])])
    provider = FakeProvider({GeneratedSectionsOutput: output})
    metrics = [MetricForPrompt(label="BLEU", value="2", display_value="+2")]

    sections = await generate_technical_sections(provider, claims=[_CLAIM_1, _CLAIM_2], metrics=metrics, model="m")

    assert sections == output.sections


async def test_generate_technical_sections_rejects_unknown_claim_id() -> None:
    fabricated_id = uuid.uuid4()
    output = GeneratedSectionsOutput(sections=[GeneratedSectionDraft(heading="Method", body="Details.", claim_ids=[fabricated_id])])
    provider = FakeProvider({GeneratedSectionsOutput: output})

    with pytest.raises(SectionReferencesUnknownClaimError):
        await generate_technical_sections(provider, claims=[_CLAIM_1], metrics=[], model="m")


async def test_generate_technical_sections_filters_prompt_to_relevant_claim_kinds() -> None:
    """method/reported-result/background feed the prompt; a limitation claim
    does not -- but claim_id validation still checks against the full claim
    set passed in, not just the filtered prompt subset (technical.py's
    module docstring)."""
    background_claim = ClaimForPrompt(
        id=uuid.uuid4(), kind=ClaimKind.background, statement="Prior work used RNNs.", excerpts=["prior work used RNNs"]
    )
    limitation_claim = ClaimForPrompt(
        id=uuid.uuid4(), kind=ClaimKind.limitation, statement="Requires large compute.", excerpts=["requires large compute"]
    )
    output = GeneratedSectionsOutput(
        sections=[GeneratedSectionDraft(heading="Method", body="Details.", claim_ids=[background_claim.id])]
    )
    provider = FakeProvider({GeneratedSectionsOutput: output})

    await generate_technical_sections(provider, claims=[background_claim, limitation_claim], metrics=[], model="m")

    prompt, _ = provider.calls[0]
    assert background_claim.statement in prompt
    assert limitation_claim.statement not in prompt
