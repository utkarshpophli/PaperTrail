"""Unit/integration tests for ``app.discovery.concepts`` -- the two grounding
paths a ``Concept`` can come from (ARCHITECTURE.md's Phase 6 decisions: never
a free-floating LLM claim)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.concepts import ground_concepts_from_arxiv_candidate, ground_concepts_from_paper
from app.discovery.schemas import ConceptExtractionOutput, ConceptTermDraft
from app.models.claim import VerificationStatus
from app.models.glossary_term import GlossaryTerm
from app.models.paper import Paper, ParseStatus
from app.providers.errors import StructuredOutputError
from tests.discovery.conftest import make_user
from tests.discovery.fake_provider import FakeDiscoveryProvider

ABSTRACT = (
    "We propose a new method that improves accuracy by 5% using attention layers. "
    "This approach builds on transformer architectures."
)


def _concept_draft(*, term: str, definition: str, excerpt: str) -> ConceptTermDraft:
    return ConceptTermDraft(term=term, definition=definition, excerpt=excerpt)


def _output(*drafts: ConceptTermDraft) -> ConceptExtractionOutput:
    return ConceptExtractionOutput(concepts=list(drafts))


# --- ground_concepts_from_paper (real Postgres, no LLM) ---------------------


async def test_ground_concepts_from_paper_uses_glossary_terms_with_source_excerpt(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    paper = Paper(
        user_id=user.id, title="A Paper", authors=[], source_file_path="/tmp/x.pdf", parse_status=ParseStatus.parsed
    )
    db_session.add(paper)
    await db_session.commit()
    await db_session.refresh(paper)

    db_session.add(
        GlossaryTerm(
            paper_id=paper.id,
            term="Attention",
            definition="A mechanism for weighing input features.",
            source_page=2,
            source_excerpt="attention layers",
        )
    )
    # Illustrative/unsourced term -- must be skipped (no grounding excerpt).
    db_session.add(
        GlossaryTerm(paper_id=paper.id, term="Transformer", definition="[General definition] A model family.")
    )
    await db_session.commit()

    concepts = await ground_concepts_from_paper(db_session, paper.id)

    assert len(concepts) == 1
    assert concepts[0].name == "Attention"
    assert concepts[0].source_paper_id == paper.id
    assert concepts[0].source_arxiv_id is None
    assert concepts[0].grounding_excerpt == "attention layers"
    assert concepts[0].verification_status == VerificationStatus.verified


async def test_ground_concepts_from_paper_sanitizes_generated_text(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    paper = Paper(
        user_id=user.id, title="A Paper", authors=[], source_file_path="/tmp/x.pdf", parse_status=ParseStatus.parsed
    )
    db_session.add(paper)
    await db_session.commit()
    await db_session.refresh(paper)

    db_session.add(
        GlossaryTerm(
            paper_id=paper.id,
            term="<script>bad</script>Attention",
            definition="<script>alert(1)</script>A mechanism for weighing input features.",
            source_page=2,
            source_excerpt="attention layers",
        )
    )
    await db_session.commit()

    concepts = await ground_concepts_from_paper(db_session, paper.id)

    assert len(concepts) == 1
    assert "<script" not in concepts[0].name
    assert "<script" not in concepts[0].description


async def test_ground_concepts_from_paper_returns_empty_for_paper_with_no_glossary(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    paper = Paper(
        user_id=user.id, title="A Paper", authors=[], source_file_path="/tmp/x.pdf", parse_status=ParseStatus.parsed
    )
    db_session.add(paper)
    await db_session.commit()
    await db_session.refresh(paper)

    concepts = await ground_concepts_from_paper(db_session, paper.id)

    assert concepts == []


# --- ground_concepts_from_arxiv_candidate (unit, FakeDiscoveryProvider) -----


async def test_ground_concepts_from_arxiv_candidate_keeps_only_verified_excerpts() -> None:
    output = _output(
        _concept_draft(term="Attention", definition="A weighting mechanism.", excerpt="attention layers"),
        _concept_draft(term="Fabricated", definition="Doesn't exist.", excerpt="quantum teleportation network"),
        _concept_draft(term="Transformer", definition="Builds on it.", excerpt="transformer architectures"),
    )
    provider = FakeDiscoveryProvider(lambda prompt, schema: output)

    concepts = await ground_concepts_from_arxiv_candidate(
        provider, arxiv_id="2001.00001", title="A Paper", abstract=ABSTRACT, model="m"
    )

    names = {concept.name for concept in concepts}
    assert names == {"Attention", "Transformer"}
    for concept in concepts:
        assert concept.verification_status == VerificationStatus.verified
        assert concept.source_arxiv_id == "2001.00001"
        assert concept.source_paper_id is None


async def test_ground_concepts_from_arxiv_candidate_sanitizes_generated_text() -> None:
    output = _output(
        _concept_draft(
            term="<script>bad</script>Attention",
            definition="<script>alert(1)</script>A mechanism.",
            excerpt="attention layers",
        ),
        _concept_draft(term="Transformer", definition="Builds on it.", excerpt="transformer architectures"),
        _concept_draft(term="Accuracy", definition="A metric.", excerpt="improves accuracy by 5%"),
    )
    provider = FakeDiscoveryProvider(lambda prompt, schema: output)

    concepts = await ground_concepts_from_arxiv_candidate(
        provider, arxiv_id="2001.00001", title="A Paper", abstract=ABSTRACT, model="m"
    )

    attention_concept = next(concept for concept in concepts if "Attention" in concept.name)
    assert "<script" not in attention_concept.name
    assert "<script" not in attention_concept.description


async def test_ground_concepts_from_arxiv_candidate_propagates_structured_output_error() -> None:
    def raising_response_fn(prompt: str, schema: type) -> ConceptExtractionOutput:
        raise StructuredOutputError("bad schema")

    provider = FakeDiscoveryProvider(raising_response_fn)

    with pytest.raises(StructuredOutputError):
        await ground_concepts_from_arxiv_candidate(provider, arxiv_id="2001.00001", title="A Paper", abstract=ABSTRACT, model="m")
