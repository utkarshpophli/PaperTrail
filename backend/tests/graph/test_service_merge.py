"""Integration tests (real Postgres) for ``build_library_graph``/
``build_paper_neighbors_graph`` merging live ``semantically_similar`` edges
with persisted ``CitationEdge`` rows.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph import service as graph_service
from app.models.citation_edge import CitationEdge
from app.models.paper import Paper, ParseStatus
from tests.discovery.fake_provider import FakeDiscoveryProvider
from tests.graph.conftest import make_analyzed_paper, make_user


async def test_merges_citation_and_similarity_edges(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    paper_a = await make_analyzed_paper(db_session, user.id, "A", "diffusion models for images", "summary A")
    paper_b = await make_analyzed_paper(db_session, user.id, "B", "diffusion models for images too", "summary B")
    paper_c = await make_analyzed_paper(db_session, user.id, "C", "unrelated topic entirely", "summary C")
    db_session.add_all(
        [
            # Same pair as the similarity edge: both signals must coexist.
            CitationEdge(user_id=user.id, from_paper_id=paper_a.id, to_paper_id=paper_b.id, relation="cites",
                         confidence=1.0, openalex_work_id="W_B"),
            CitationEdge(user_id=user.id, from_paper_id=paper_c.id, to_paper_id=paper_a.id, relation="extends",
                         confidence=0.8, openalex_work_id="W_A"),
        ]
    )
    await db_session.commit()
    embeddings = {
        "diffusion models for images summary A": [1.0, 0.0],
        "diffusion models for images too summary B": [0.99, 0.14],
        "unrelated topic entirely summary C": [0.0, 1.0],
    }
    provider = FakeDiscoveryProvider(response_fn=lambda p, s: s(), embeddings=embeddings)

    graph = await graph_service.build_library_graph(db_session, provider, user.id, embed_model="m")

    by_key = {(e.source, e.target, e.relation): e.weight for e in graph.edges}
    a, b, c = str(paper_a.id), str(paper_b.id), str(paper_c.id)
    assert by_key[(a, b, "cites")] == 1.0
    assert by_key[(c, a, "extends")] == 0.8
    assert (a, b, "semantically_similar") in by_key
    assert len(graph.edges) == 3
    # Citation edges come first (grounded facts), similarity fills the rest.
    assert graph.edges[-1].relation == "semantically_similar"


async def test_cap_applies_to_combined_set_citations_first(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await make_user(db_session)
    paper_a = await make_analyzed_paper(db_session, user.id, "A", "same", "s")
    paper_b = await make_analyzed_paper(db_session, user.id, "B", "same", "s")
    db_session.add(CitationEdge(user_id=user.id, from_paper_id=paper_a.id, to_paper_id=paper_b.id, openalex_work_id="W"))
    await db_session.commit()
    monkeypatch.setattr(graph_service, "_MAX_EDGES", 1)
    provider = FakeDiscoveryProvider(response_fn=lambda p, s: s(), embeddings={"same s": [1.0, 0.0]})

    graph = await graph_service.build_library_graph(db_session, provider, user.id, embed_model="m")

    assert [e.relation for e in graph.edges] == ["cites"]


async def test_adds_nodes_for_unanalyzed_citation_endpoints(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    analyzed = await make_analyzed_paper(db_session, user.id, "Analyzed", "t", "s")
    bare = Paper(user_id=user.id, title="No evidence yet", authors=[], source_file_path="/tmp/y.pdf",
                 parse_status=ParseStatus.parsed)
    db_session.add(bare)
    await db_session.commit()
    db_session.add(CitationEdge(user_id=user.id, from_paper_id=analyzed.id, to_paper_id=bare.id, openalex_work_id="W"))
    await db_session.commit()
    provider = FakeDiscoveryProvider(response_fn=lambda p, s: s())

    graph = await graph_service.build_library_graph(db_session, provider, user.id, embed_model="m")

    assert {n.id for n in graph.nodes} == {str(analyzed.id), str(bare.id)}
    assert len(graph.edges) == 1


async def test_ignores_other_users_citation_edges(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    other = await make_user(db_session)
    x = await make_analyzed_paper(db_session, other.id, "X", "t", "s")
    y = await make_analyzed_paper(db_session, other.id, "Y", "t", "s")
    db_session.add(CitationEdge(user_id=other.id, from_paper_id=x.id, to_paper_id=y.id, openalex_work_id="W"))
    await db_session.commit()
    provider = FakeDiscoveryProvider(response_fn=lambda p, s: s())

    graph = await graph_service.build_library_graph(db_session, provider, user.id, embed_model="m")

    assert graph.edges == [] and graph.nodes == []


async def test_neighbors_graph_includes_citation_edges_touching_the_paper(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    a = await make_analyzed_paper(db_session, user.id, "A", "t a", "s")
    b = await make_analyzed_paper(db_session, user.id, "B", "t b", "s")
    c = await make_analyzed_paper(db_session, user.id, "C", "t c", "s")
    db_session.add_all(
        [
            CitationEdge(user_id=user.id, from_paper_id=a.id, to_paper_id=b.id, openalex_work_id="W1"),
            CitationEdge(user_id=user.id, from_paper_id=b.id, to_paper_id=c.id, openalex_work_id="W2"),
        ]
    )
    await db_session.commit()
    provider = FakeDiscoveryProvider(response_fn=lambda p, s: s())

    graph = await graph_service.build_paper_neighbors_graph(db_session, provider, user.id, a.id, embed_model="m")

    assert [(e.source, e.target, e.relation) for e in graph.edges] == [(str(a.id), str(b.id), "cites")]
    assert {n.id for n in graph.nodes} == {str(a.id), str(b.id)}
