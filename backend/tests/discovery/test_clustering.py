"""Unit tests for ``app.discovery.clustering``."""

import pytest

from app.discovery.clustering import cluster_landscape
from app.discovery.exceptions import ClusterReferencesUnknownPaperError
from app.discovery.schemas import (
    ClusterAssignmentDraft,
    ExtractedField,
    LandscapeClusteringOutput,
    PaperExtractionCard,
)
from app.models.claim import VerificationStatus
from app.papers.arxiv_client import ArxivMetadata
from tests.discovery.fake_provider import FakeDiscoveryProvider


def _paper(arxiv_id: str) -> ArxivMetadata:
    return ArxivMetadata(
        arxiv_id=arxiv_id, title=f"Title {arxiv_id}", authors=[], year=2024, pdf_url="https://arxiv.org/pdf/x",
        abstract="An abstract.",
    )


def _card() -> PaperExtractionCard:
    field = ExtractedField(text="summary", verification_status=VerificationStatus.verified)
    return PaperExtractionCard(tldr=field, problem=field, method=field, results=field, why_it_matters=field)


async def test_cluster_landscape_returns_valid_clusters() -> None:
    papers = [_paper("2001.00001"), _paper("2001.00002")]
    cards = [_card(), _card()]
    output = LandscapeClusteringOutput(
        overview="An overview of the landscape.",
        clusters=[
            ClusterAssignmentDraft(label="Cluster A", description="Papers using method A.", arxiv_ids=["2001.00001"]),
            ClusterAssignmentDraft(label="Cluster B", description="Papers using method B.", arxiv_ids=["2001.00002"]),
        ],
    )

    provider = FakeDiscoveryProvider(lambda prompt, schema: output)

    result = await cluster_landscape(provider, papers, cards, model="m")

    assert len(result.clusters) == 2
    assert result.overview == "An overview of the landscape."


async def test_cluster_landscape_rejects_unknown_arxiv_id() -> None:
    papers = [_paper("2001.00001")]
    cards = [_card()]
    output = LandscapeClusteringOutput(
        overview="An overview.",
        clusters=[
            ClusterAssignmentDraft(label="Cluster A", description="desc", arxiv_ids=["2001.00001"]),
            ClusterAssignmentDraft(label="Cluster B", description="desc", arxiv_ids=["9999.99999"]),
        ],
    )
    provider = FakeDiscoveryProvider(lambda prompt, schema: output)

    with pytest.raises(ClusterReferencesUnknownPaperError):
        await cluster_landscape(provider, papers, cards, model="m")


async def test_cluster_landscape_sanitizes_generated_text() -> None:
    papers = [_paper("2001.00001"), _paper("2001.00002")]
    cards = [_card(), _card()]
    output = LandscapeClusteringOutput(
        overview="<script>alert(1)</script>An overview.",
        clusters=[
            ClusterAssignmentDraft(
                label="Cluster A", description="<script>bad</script>desc", arxiv_ids=["2001.00001"]
            ),
            ClusterAssignmentDraft(label="Cluster B", description="desc", arxiv_ids=["2001.00002"]),
        ],
    )
    provider = FakeDiscoveryProvider(lambda prompt, schema: output)

    result = await cluster_landscape(provider, papers, cards, model="m")

    assert "<script" not in result.overview
    assert "<script" not in result.clusters[0].description
