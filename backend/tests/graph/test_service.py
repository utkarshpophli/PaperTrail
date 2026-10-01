"""Unit tests for the pure edge-building logic (threshold + cap, no DB), and
integration tests against real Postgres ``Paper``/``Evidence`` rows
(TESTING.md: real fixtures over mocks for the thing under test).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph import service as graph_service
from app.models.paper import Paper, ParseStatus
from app.papers.exceptions import PaperNotFoundError
from app.providers.errors import NotSupportedError
from tests.discovery.fake_provider import FakeDiscoveryProvider
from tests.graph.conftest import make_analyzed_paper, make_user


def _paper(title: str) -> Paper:
    return Paper(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title=title,
        authors=[],
        source_file_path="/tmp/x.pdf",
        parse_status=ParseStatus.parsed,
    )


# ---- _build_edges: pure unit tests, no DB ----------------------------------


def test_build_edges_only_above_threshold() -> None:
    papers = [_paper("A"), _paper("B"), _paper("C")]
    vectors = [
        [1.0, 0.0],  # A
        [0.99, 0.14],  # B -- close to A, above threshold
        [0.0, 1.0],  # C -- orthogonal to A, below threshold
    ]

    edges = graph_service._build_edges(papers, vectors)

    pairs = {frozenset((edge.source, edge.target)) for edge in edges}
    assert frozenset((str(papers[0].id), str(papers[1].id))) in pairs
    assert frozenset((str(papers[0].id), str(papers[2].id))) not in pairs
    assert frozenset((str(papers[1].id), str(papers[2].id))) not in pairs


def test_build_edges_sorted_descending_by_weight() -> None:
    papers = [_paper("A"), _paper("B"), _paper("C")]
    vectors = [[1.0, 0.0], [0.95, 0.31], [1.0, 0.02]]  # A~C closer than A~B

    edges = graph_service._build_edges(papers, vectors)

    weights = [edge.weight for edge in edges]
    assert weights == sorted(weights, reverse=True)


def test_build_edges_caps_total_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_service, "_MAX_EDGES", 2)
    papers = [_paper(str(i)) for i in range(5)]
    # Identical vectors -- every pair is a perfect-similarity edge.
    vectors = [[1.0, 0.0] for _ in papers]

    edges = graph_service._build_edges(papers, vectors)

    assert len(edges) == 2


def test_build_edges_empty_below_threshold_for_all_pairs() -> None:
    papers = [_paper("A"), _paper("B")]
    vectors = [[1.0, 0.0], [0.0, 1.0]]

    edges = graph_service._build_edges(papers, vectors)

    assert edges == []


# ---- build_library_graph / build_paper_neighbors_graph: real Postgres -----


async def test_build_library_graph_excludes_unanalyzed_papers(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    analyzed = await make_analyzed_paper(db_session, user.id, "Analyzed", "thesis text", "summary text")
    unanalyzed = Paper(
        user_id=user.id,
        title="No evidence yet",
        authors=[],
        source_file_path="/tmp/y.pdf",
        parse_status=ParseStatus.parsed,
    )
    db_session.add(unanalyzed)
    await db_session.commit()

    provider = FakeDiscoveryProvider(response_fn=lambda p, s: s(), embeddings={"thesis text summary text": [1.0, 0.0]})

    graph = await graph_service.build_library_graph(db_session, provider, user.id, embed_model="m")

    node_ids = {node.id for node in graph.nodes}
    assert str(analyzed.id) in node_ids
    assert str(unanalyzed.id) not in node_ids


async def test_build_library_graph_produces_edge_for_similar_papers(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    paper_a = await make_analyzed_paper(db_session, user.id, "A", "diffusion models for images", "summary A")
    paper_b = await make_analyzed_paper(db_session, user.id, "B", "diffusion models for images too", "summary B")
    paper_c = await make_analyzed_paper(db_session, user.id, "C", "unrelated topic entirely", "summary C")

    embeddings = {
        "diffusion models for images summary A": [1.0, 0.0],
        "diffusion models for images too summary B": [0.99, 0.14],
        "unrelated topic entirely summary C": [0.0, 1.0],
    }
    provider = FakeDiscoveryProvider(response_fn=lambda p, s: s(), embeddings=embeddings)

    graph = await graph_service.build_library_graph(db_session, provider, user.id, embed_model="m")

    assert len(graph.nodes) == 3
    pairs = {frozenset((edge.source, edge.target)) for edge in graph.edges}
    assert frozenset((str(paper_a.id), str(paper_b.id))) in pairs
    assert frozenset((str(paper_a.id), str(paper_c.id))) not in pairs
    for edge in graph.edges:
        assert edge.relation == "semantically_similar"


async def test_build_library_graph_propagates_not_supported_error(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await make_analyzed_paper(db_session, user.id, "A", "thesis", "summary")

    provider = FakeDiscoveryProvider(
        response_fn=lambda p, s: s(), embed_error=NotSupportedError("This provider cannot embed")
    )

    with pytest.raises(NotSupportedError):
        await graph_service.build_library_graph(db_session, provider, user.id, embed_model="m")


async def test_build_library_graph_empty_library_returns_empty_graph(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    provider = FakeDiscoveryProvider(response_fn=lambda p, s: s())

    graph = await graph_service.build_library_graph(db_session, provider, user.id, embed_model="m")

    assert graph.nodes == []
    assert graph.edges == []
    assert provider.embed_calls == []


async def test_build_paper_neighbors_graph_scoped_to_one_paper(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    paper_a = await make_analyzed_paper(db_session, user.id, "A", "topic X", "summary A")
    paper_b = await make_analyzed_paper(db_session, user.id, "B", "topic X too", "summary B")
    paper_c = await make_analyzed_paper(db_session, user.id, "C", "topic X as well", "summary C")

    embeddings = {
        "topic X summary A": [1.0, 0.0],
        "topic X too summary B": [0.99, 0.14],
        "topic X as well summary C": [0.98, 0.19],
    }
    provider = FakeDiscoveryProvider(response_fn=lambda p, s: s(), embeddings=embeddings)

    graph = await graph_service.build_paper_neighbors_graph(db_session, provider, user.id, paper_a.id, embed_model="m")

    node_ids = {node.id for node in graph.nodes}
    assert str(paper_a.id) in node_ids
    for edge in graph.edges:
        assert str(paper_a.id) in (edge.source, edge.target)
    assert node_ids == {str(paper_a.id), str(paper_b.id), str(paper_c.id)}


async def test_build_paper_neighbors_graph_not_owned_is_404(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    other_user = await make_user(db_session)
    paper = await make_analyzed_paper(db_session, owner.id, "A", "thesis", "summary")

    provider = FakeDiscoveryProvider(response_fn=lambda p, s: s())

    with pytest.raises(PaperNotFoundError):
        await graph_service.build_paper_neighbors_graph(db_session, provider, other_user.id, paper.id, embed_model="m")
