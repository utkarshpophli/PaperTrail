"""Library-wide semantic-similarity literature graph (Phase 7).

Computed live per request -- no persistence table, since a library's paper
set and embeddings change too often for a cached snapshot to earn its
staleness (ARCHITECTURE.md's Phase 7 decisions). Only papers with a
completed Evidence stage are considered; an unanalyzed paper simply doesn't
appear yet.

``semantically_similar`` edges are computed live, every request, as
described above. ``cites``/refined-relation edges (Phase 7 slice 2,
``app.graph.citations``) are the opposite: persisted ``CitationEdge`` rows,
fetched only by an explicit "refresh citations" user action, since an
OpenAlex lookup is a real external API call unlike an in-process embedding
comparison. ``build_library_graph`` merges both into one response --
citation edges first (grounded external facts), semantically-similar edges
filling the remaining ``_MAX_EDGES`` budget -- documenting the merge/
truncation order ARCHITECTURE.md leaves as an implementation call. Both edge
types can coexist between the same paper pair; no deduplication is
attempted, since a citation fact and an independent similarity signal are
both real, distinct pieces of information.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.ranking import cosine_similarity
from app.graph.citations import get_cached_citation_edges
from app.graph.schemas import GraphEdge, GraphNode, LibraryGraphResponse
from app.models.citation_edge import CitationEdge
from app.models.evidence import Evidence
from app.models.paper import Paper
from app.papers.service import get_owned_paper
from app.providers.base import AIProvider

# Below this cosine similarity, two papers' theses aren't considered related
# enough to draw an edge -- avoids returning a dense clique for a library
# where most AI/ML papers are loosely similar to each other regardless of
# topic (ARCHITECTURE.md's Phase 7 decisions). Not tuned against real usage
# data -- revisit if it under/over-connects a real library.
_SIMILARITY_THRESHOLD = 0.7
# Same "cap the response size" precedent as Roadmap.edges' max_length=200
# (Phase 6) -- protects a large library from producing a huge edge set.
_MAX_EDGES = 200
# No cluster concept exists at library scope (unlike a TopicLandscape's
# MethodClusters) -- every node gets the same color for now.
_NODE_COLOR = "#6366f1"


def _embedding_text(evidence: Evidence) -> str:
    # thesis + plain_summary gives the embedding more signal than the thesis
    # alone -- a one-line thesis is often too terse to separate genuinely
    # different papers on a similar topic.
    return f"{evidence.thesis} {evidence.plain_summary}"


async def _owned_analyzed_papers(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[Paper, Evidence]]:
    result = await db.execute(
        select(Paper, Evidence).join(Evidence, Evidence.paper_id == Paper.id).where(Paper.user_id == user_id)
    )
    return [(paper, evidence) for paper, evidence in result.all()]


def _build_edges(papers: list[Paper], vectors: list[list[float]]) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    for i in range(len(papers)):
        for j in range(i + 1, len(papers)):
            similarity = cosine_similarity(vectors[i], vectors[j])
            if similarity >= _SIMILARITY_THRESHOLD:
                edges.append(GraphEdge(source=str(papers[i].id), target=str(papers[j].id), weight=similarity))
    edges.sort(key=lambda edge: edge.weight or 0.0, reverse=True)
    return edges[:_MAX_EDGES]


def _citation_edges_to_graph_edges(rows: list[CitationEdge]) -> list[GraphEdge]:
    return [
        GraphEdge(source=str(row.from_paper_id), target=str(row.to_paper_id), relation=row.relation, weight=row.confidence)
        for row in rows
    ]


async def _nodes_for_edges(
    db: AsyncSession, user_id: uuid.UUID, nodes: list[GraphNode], edges: list[GraphEdge]
) -> list[GraphNode]:
    """Ensures every edge endpoint has a matching node -- a ``CitationEdge``
    can reference a paper with no completed Evidence stage yet (citation
    fetching only needs ``Paper.doi``/``title``, unlike the similarity
    edges above), which would otherwise leave a dangling edge with no node
    to render at either end.
    """
    known_ids = {node.id for node in nodes}
    referenced_ids = {endpoint for edge in edges for endpoint in (edge.source, edge.target)}
    missing_ids = referenced_ids - known_ids
    if not missing_ids:
        return nodes

    missing_uuids = [uuid.UUID(mid) for mid in missing_ids]
    extra_papers = await db.scalars(select(Paper).where(Paper.id.in_(missing_uuids), Paper.user_id == user_id))
    extra_nodes = [GraphNode(id=str(paper.id), label=paper.title, color=_NODE_COLOR) for paper in extra_papers]
    return nodes + extra_nodes


async def build_library_graph(
    db: AsyncSession, provider: AIProvider, user_id: uuid.UUID, *, embed_model: str
) -> LibraryGraphResponse:
    """``NotSupportedError`` from ``provider.embed`` propagates unhandled to
    the caller -- no silent fallback to a different provider, same
    discipline as ``app.discovery.ranking``."""
    pairs = await _owned_analyzed_papers(db, user_id)

    nodes: list[GraphNode] = []
    similarity_edges: list[GraphEdge] = []
    if pairs:
        papers = [paper for paper, _evidence in pairs]
        texts = [_embedding_text(evidence) for _paper, evidence in pairs]
        vectors = await provider.embed(texts, model=embed_model)
        nodes = [GraphNode(id=str(paper.id), label=paper.title, color=_NODE_COLOR) for paper in papers]
        similarity_edges = _build_edges(papers, vectors)

    citation_rows = await get_cached_citation_edges(db, user_id)
    citation_edges = _citation_edges_to_graph_edges(citation_rows)

    # Citation edges first (grounded external facts), semantically_similar
    # filling whatever budget remains -- see this module's docstring.
    edges = (citation_edges + similarity_edges)[:_MAX_EDGES]
    nodes = await _nodes_for_edges(db, user_id, nodes, edges)
    return LibraryGraphResponse(nodes=nodes, edges=edges)


async def build_paper_neighbors_graph(
    db: AsyncSession, provider: AIProvider, user_id: uuid.UUID, paper_id: uuid.UUID, *, embed_model: str
) -> LibraryGraphResponse:
    """Scoped to one paper's direct edges -- ownership-checked (404 if the
    paper isn't owned by the requester), same discipline as
    ``app.papers.service.get_owned_paper``'s every other call site.

    ponytail: recomputes the whole library's embeddings/edges and filters,
    rather than a query scoped up front -- same embed cost either way since
    finding "papers similar to X" requires embedding every candidate
    regardless; simplest correct implementation given no embeddings are
    persisted. Revisit only if per-paper neighbor lookups on a large library
    become a measured latency/cost problem.
    """
    await get_owned_paper(db, paper_id, user_id)

    full_graph = await build_library_graph(db, provider, user_id, embed_model=embed_model)
    paper_id_str = str(paper_id)
    neighbor_edges = [edge for edge in full_graph.edges if paper_id_str in (edge.source, edge.target)]
    neighbor_ids = {edge.source for edge in neighbor_edges} | {edge.target for edge in neighbor_edges}
    neighbor_ids.add(paper_id_str)
    nodes = [node for node in full_graph.nodes if node.id in neighbor_ids]
    return LibraryGraphResponse(nodes=nodes, edges=neighbor_edges)
