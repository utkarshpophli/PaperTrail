"""The one-repair-retry for claim ids a schema can't check (Application Guide
section citing a claim id that does not exist, seen live on EnvHarness)."""

import uuid

import pytest
from pydantic import BaseModel

from app.evidence.exceptions import SectionReferencesUnknownClaimError
from app.evidence.learning import generate_application_guide_sections
from app.evidence.schemas import ClaimForPrompt, GeneratedSectionDraft, GeneratedSectionsOutput
from app.models.claim import ClaimKind, VerificationStatus

REAL = uuid.uuid4()
FAKE = uuid.uuid4()
CLAIM = ClaimForPrompt(
    id=REAL, kind=ClaimKind.method, statement="s", excerpts=["e"], verification_status=VerificationStatus.verified
)


def _sections(claim_id: uuid.UUID) -> GeneratedSectionsOutput:
    return GeneratedSectionsOutput(
        sections=[GeneratedSectionDraft(heading="What Results to Expect", body="b", claim_ids=[claim_id])]
    )


class _Sequenced:
    def __init__(self, *outputs: BaseModel) -> None:
        self._outputs = list(outputs)
        self.prompts: list[str] = []

    async def generate(self, prompt: str, schema: type[BaseModel], **opts: object) -> BaseModel:
        self.prompts.append(prompt)
        return self._outputs.pop(0)


async def test_unknown_claim_id_gets_one_retry_with_the_error_fed_back() -> None:
    provider = _Sequenced(_sections(FAKE), _sections(REAL))

    sections = await generate_application_guide_sections(provider, claims=[CLAIM], metrics=[], model="m")

    assert [s.claim_ids for s in sections] == [[REAL]]
    assert len(provider.prompts) == 2
    assert str(FAKE) in provider.prompts[1] and "unknown claim_id" in provider.prompts[1]


async def test_second_unknown_claim_id_still_raises_and_nothing_is_returned() -> None:
    provider = _Sequenced(_sections(FAKE), _sections(FAKE))

    with pytest.raises(SectionReferencesUnknownClaimError):
        await generate_application_guide_sections(provider, claims=[CLAIM], metrics=[], model="m")
    assert len(provider.prompts) == 2
