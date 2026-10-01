"""Unit tests for ``app.discovery.prerequisites`` -- the "known ids" edge
filtering discipline (mirrors ``app.evidence.assistant``'s claim-id
filtering: an edge referencing a concept outside the grounded set is dropped
with a logged warning, never raised)."""

import logging

import pytest

from app.discovery.prerequisites import propose_prerequisite_edges
from app.discovery.schemas import Concept, PrerequisiteEdgeDraft, PrerequisiteExtractionOutput
from app.models.claim import VerificationStatus
from app.providers.errors import StructuredOutputError
from tests.discovery.fake_provider import FakeDiscoveryProvider


def _concept(concept_id: str, name: str) -> Concept:
    return Concept(
        id=concept_id,
        name=name,
        description=f"{name} description",
        source_arxiv_id="2001.00001",
        grounding_excerpt="an excerpt",
        verification_status=VerificationStatus.verified,
    )


async def test_propose_prerequisite_edges_keeps_edges_between_known_concepts() -> None:
    concepts = [_concept("c1", "Attention"), _concept("c2", "Transformer")]
    output = PrerequisiteExtractionOutput(
        edges=[PrerequisiteEdgeDraft(concept_id="c2", prerequisite_concept_id="c1")]
    )
    provider = FakeDiscoveryProvider(lambda prompt, schema: output)

    edges = await propose_prerequisite_edges(provider, concepts, model="m")

    assert len(edges) == 1
    assert edges[0].concept_id == "c2"
    assert edges[0].prerequisite_concept_id == "c1"


async def test_propose_prerequisite_edges_drops_edge_referencing_unknown_concept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    concepts = [_concept("c1", "Attention"), _concept("c2", "Transformer")]
    output = PrerequisiteExtractionOutput(
        edges=[
            PrerequisiteEdgeDraft(concept_id="c2", prerequisite_concept_id="c1"),
            PrerequisiteEdgeDraft(concept_id="c2", prerequisite_concept_id="unknown-id"),
        ]
    )
    provider = FakeDiscoveryProvider(lambda prompt, schema: output)

    # app.core.logging.get_logger sets propagate=False, so caplog (which only
    # listens on the root logger by default) needs its handler attached
    # directly to this named logger -- same pattern as
    # tests/evidence/test_assistant.py's claim-id-filtering test.
    target_logger = logging.getLogger("app.discovery.prerequisites")
    target_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="app.discovery.prerequisites"):
            edges = await propose_prerequisite_edges(provider, concepts, model="m")
    finally:
        target_logger.removeHandler(caplog.handler)

    assert len(edges) == 1
    assert edges[0].prerequisite_concept_id == "c1"
    assert any("unknown_concept" in record.getMessage() for record in caplog.records)


async def test_propose_prerequisite_edges_drops_self_referencing_edge() -> None:
    concepts = [_concept("c1", "Attention"), _concept("c2", "Transformer")]
    output = PrerequisiteExtractionOutput(
        edges=[PrerequisiteEdgeDraft(concept_id="c1", prerequisite_concept_id="c1")]
    )
    provider = FakeDiscoveryProvider(lambda prompt, schema: output)

    edges = await propose_prerequisite_edges(provider, concepts, model="m")

    assert edges == []


async def test_propose_prerequisite_edges_deduplicates_repeated_edges() -> None:
    concepts = [_concept("c1", "Attention"), _concept("c2", "Transformer")]
    output = PrerequisiteExtractionOutput(
        edges=[
            PrerequisiteEdgeDraft(concept_id="c2", prerequisite_concept_id="c1"),
            PrerequisiteEdgeDraft(concept_id="c2", prerequisite_concept_id="c1"),
        ]
    )
    provider = FakeDiscoveryProvider(lambda prompt, schema: output)

    edges = await propose_prerequisite_edges(provider, concepts, model="m")

    assert len(edges) == 1


async def test_propose_prerequisite_edges_returns_empty_without_calling_provider_for_single_concept() -> None:
    provider = FakeDiscoveryProvider(lambda prompt, schema: (_ for _ in ()).throw(AssertionError("should not call")))

    edges = await propose_prerequisite_edges(provider, [_concept("c1", "Attention")], model="m")

    assert edges == []
    assert provider.generate_calls == []


async def test_propose_prerequisite_edges_propagates_structured_output_error() -> None:
    def raising_response_fn(prompt: str, schema: type) -> PrerequisiteExtractionOutput:
        raise StructuredOutputError("bad schema")

    provider = FakeDiscoveryProvider(raising_response_fn)

    with pytest.raises(StructuredOutputError):
        await propose_prerequisite_edges(provider, [_concept("c1", "Attention"), _concept("c2", "Transformer")], model="m")
