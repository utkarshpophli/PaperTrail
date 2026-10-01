"""Unit tests for ``app.discovery.ranking`` -- embedding-based cosine
similarity re-rank (never keyword match)."""

import pytest

from app.discovery.ranking import rank_candidates_by_topic, rank_candidates_for_profile
from app.papers.arxiv_client import ArxivMetadata
from app.providers.errors import NotSupportedError
from tests.discovery.fake_provider import FakeDiscoveryProvider


def _paper(arxiv_id: str, abstract: str, title: str | None = None) -> ArxivMetadata:
    return ArxivMetadata(
        arxiv_id=arxiv_id,
        title=title or arxiv_id,
        authors=["Author"],
        year=2024,
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        abstract=abstract,
    )


def _unused_response_fn(prompt: str, schema: type) -> None:
    raise AssertionError("ranking must not call generate()")


async def test_rank_candidates_by_topic_orders_by_cosine_similarity() -> None:
    close_paper = _paper("2001.00001", "diffusion models for image generation")
    far_paper = _paper("2001.00002", "compilers for functional programming languages")
    embeddings = {
        "diffusion models": [1.0, 0.0],
        "diffusion models for image generation": [0.99, 0.05],
        "compilers for functional programming languages": [0.0, 1.0],
    }
    provider = FakeDiscoveryProvider(_unused_response_fn, embeddings=embeddings)

    ranked = await rank_candidates_by_topic(provider, "diffusion models", [far_paper, close_paper], embed_model="m", top_n=15)

    assert [item.paper.arxiv_id for item in ranked] == ["2001.00001", "2001.00002"]
    assert ranked[0].relevance_score > ranked[1].relevance_score


async def test_rank_candidates_by_topic_respects_top_n() -> None:
    papers = [_paper(f"200{i}.0000{i}", f"paper about topic {i}") for i in range(5)]
    provider = FakeDiscoveryProvider(_unused_response_fn, embeddings={})  # all zero vectors -> score 0.0 for all

    ranked = await rank_candidates_by_topic(provider, "topic", papers, embed_model="m", top_n=2)

    assert len(ranked) == 2


async def test_rank_candidates_by_topic_empty_candidates_skips_embed_call() -> None:
    provider = FakeDiscoveryProvider(_unused_response_fn)

    ranked = await rank_candidates_by_topic(provider, "topic", [], embed_model="m")

    assert ranked == []
    assert provider.embed_calls == []


async def test_rank_candidates_by_topic_propagates_not_supported_error() -> None:
    provider = FakeDiscoveryProvider(_unused_response_fn, embed_error=NotSupportedError("no embed"))

    with pytest.raises(NotSupportedError):
        await rank_candidates_by_topic(provider, "topic", [_paper("2001.00001", "abstract")], embed_model="m")


async def test_rank_candidates_for_profile_grounds_explanation_signal_in_best_match() -> None:
    matching_paper = _paper("2001.00001", "reinforcement learning for robotics")
    other_paper = _paper("2001.00002", "database indexing structures")
    embeddings = {
        "reinforcement learning": [1.0, 0.0],
        "compilers": [0.0, 1.0],
        "reinforcement learning for robotics": [1.0, 0.0],
        "database indexing structures": [0.5, 0.5],
    }
    provider = FakeDiscoveryProvider(_unused_response_fn, embeddings=embeddings)

    ranked = await rank_candidates_for_profile(
        provider,
        interests=["reinforcement learning"],
        goals=["compilers"],
        candidates=[other_paper, matching_paper],
        embed_model="m",
    )

    top = ranked[0]
    assert top.paper.arxiv_id == "2001.00001"
    assert top.matched_signal_kind == "interest"
    assert top.matched_signal_text == "reinforcement learning"


async def test_rank_candidates_for_profile_no_signals_returns_empty() -> None:
    provider = FakeDiscoveryProvider(_unused_response_fn)

    ranked = await rank_candidates_for_profile(
        provider, interests=[], goals=[], candidates=[_paper("2001.00001", "abstract")], embed_model="m"
    )

    assert ranked == []
    assert provider.embed_calls == []
