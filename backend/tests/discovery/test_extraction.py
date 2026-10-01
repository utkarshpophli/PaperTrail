"""Unit tests for ``app.discovery.extraction`` -- per-paper lightweight
extraction, with excerpts independently verified against the paper's own
abstract via ``app.evidence.verifier`` (never trusted on the model's
self-report)."""

import pytest

from app.discovery.extraction import extract_paper_card, extract_paper_cards
from app.discovery.schemas import ExtractionFieldDraft, PaperExtractionCardDraft
from app.models.claim import VerificationStatus
from app.providers.errors import StructuredOutputError
from tests.discovery.fake_provider import FakeDiscoveryProvider

ABSTRACT = (
    "We propose a new method that improves accuracy by 5% over the prior baseline. "
    "This method uses attention layers to weigh input features."
)


def _draft_with_excerpts(good_excerpt: str, bad_excerpt: str) -> PaperExtractionCardDraft:
    good_field = ExtractionFieldDraft(text="A short summary.", excerpt=good_excerpt)
    bad_field = ExtractionFieldDraft(text="An unsupported summary.", excerpt=bad_excerpt)
    return PaperExtractionCardDraft(
        tldr=good_field, problem=good_field, method=good_field, results=good_field, why_it_matters=bad_field
    )


async def test_extract_paper_card_verifies_excerpt_against_abstract() -> None:
    draft = _draft_with_excerpts(
        good_excerpt="improves accuracy by 5% over the prior baseline",
        bad_excerpt="quantum teleportation over a fiber optic network",
    )

    def response_fn(prompt: str, schema: type) -> PaperExtractionCardDraft:
        assert schema is PaperExtractionCardDraft
        return draft

    provider = FakeDiscoveryProvider(response_fn)

    card = await extract_paper_card(provider, title="A Paper", abstract=ABSTRACT, model="m")

    assert card.tldr.verification_status == VerificationStatus.verified
    # The excerpt bears no resemblance to the abstract -- must never be
    # silently upgraded to verified/partially-matched.
    assert card.why_it_matters.verification_status in (
        VerificationStatus.mismatch,
        VerificationStatus.not_found,
    )


async def test_extract_paper_card_empty_abstract_marks_needs_review() -> None:
    draft = _draft_with_excerpts(good_excerpt="anything", bad_excerpt="anything else")

    provider = FakeDiscoveryProvider(lambda prompt, schema: draft)

    card = await extract_paper_card(provider, title="A Paper", abstract="", model="m")

    assert card.tldr.verification_status == VerificationStatus.needs_review


async def test_extract_paper_card_propagates_structured_output_error() -> None:
    def raising_response_fn(prompt: str, schema: type) -> PaperExtractionCardDraft:
        raise StructuredOutputError("bad schema")

    provider = FakeDiscoveryProvider(raising_response_fn)

    with pytest.raises(StructuredOutputError):
        await extract_paper_card(provider, title="A Paper", abstract=ABSTRACT, model="m")


async def test_extract_paper_cards_runs_concurrently_for_every_paper() -> None:
    from app.papers.arxiv_client import ArxivMetadata

    draft = _draft_with_excerpts(good_excerpt="improves accuracy by 5%", bad_excerpt="unrelated text")
    papers = [
        ArxivMetadata(
            arxiv_id=f"2001.0000{i}",
            title=f"Paper {i}",
            authors=[],
            year=2024,
            pdf_url="https://arxiv.org/pdf/x",
            abstract=ABSTRACT,
        )
        for i in range(3)
    ]

    provider = FakeDiscoveryProvider(lambda prompt, schema: draft)

    cards = await extract_paper_cards(provider, papers, model="m")

    assert len(cards) == 3
    assert len(provider.generate_calls) == 3
