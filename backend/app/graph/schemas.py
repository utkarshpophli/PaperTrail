"""Pydantic v2 shapes for the library-wide literature graph (Phase 7). Same
generic ``{nodes, edges}`` Neural Map contract as
``app.discovery.schemas.LandscapeGraphResponse`` -- kept as a distinct class
here (not imported) so this module doesn't couple to Discovery's schema
module, matching this codebase's existing "Discovery and its future Phase 7
sibling stay decoupled" precedent (``app.discovery.service.AnalysisEvent``'s
own docstring makes the same call for the same reason).

``relation`` carries the full ``LiteratureEdge`` enum (docs/DATA_MODEL.md).
Phase 7 slice 1 only ever emitted ``"semantically_similar"``; Phase 7 slice 2
(``app.graph.citations``) adds real ``"cites"`` edges (and, when the
classifier confidently refines one, any of the other 10 non-similarity
relations) grounded in OpenAlex citation data -- see
``app.graph.service.build_library_graph``'s merge of live similarity edges
with persisted ``CitationEdge`` rows.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

LiteratureEdgeRelation = Literal[
    "cites",
    "extends",
    "improves",
    "reproduces",
    "challenges",
    "uses",
    "inspired_by",
    "benchmark",
    "dataset",
    "architecture",
    "follow_up",
    "semantically_similar",
]


class GraphNode(BaseModel):
    id: str
    label: str
    color: str
    size: float | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: LiteratureEdgeRelation = "semantically_similar"
    weight: float | None = None


class LibraryGraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class CitationEdgeResponse(BaseModel):
    """Response shape for ``POST /graph/papers/{id}/citations/refresh`` --
    the persisted ``CitationEdge`` row, not the generic ``GraphEdge`` Neural
    Map shape (``GET /graph`` converts ``CitationEdge`` rows to
    ``GraphEdge``s separately, in ``app.graph.service``) -- this response
    exists so the refresh action can show the caller exactly what was
    fetched/classified, including provenance fields (``openalex_work_id``,
    ``fetched_at``) the graph-rendering contract has no use for.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_paper_id: uuid.UUID
    to_paper_id: uuid.UUID
    relation: LiteratureEdgeRelation
    confidence: float
    openalex_work_id: str
    fetched_at: datetime
