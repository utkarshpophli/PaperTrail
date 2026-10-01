"""A cached, OpenAlex-grounded citation relationship between two of a user's
own owned papers (docs/ARCHITECTURE.md's "Phase 7 slice 2 decisions"
subsection).

Persisted, not live-recomputed like ``semantically_similar`` (see
``app.graph.service``'s module docstring for why that one stays live) -- an
OpenAlex lookup is a real external API call with real rate limits, and a
paper's citation graph doesn't change between page loads the way
embeddings-driven similarity might. Populated only by an explicit "refresh
citations" user action (``POST /graph/papers/{id}/citations/refresh``),
never a background sync -- same explicit-user-action precedent as Phase 8's
repository detection.

``relation`` is a plain ``String`` column, not a Postgres enum -- same call
as ``Repository.source``: no independent DB-level lifecycle of its own, and
``app.graph.schemas.LiteratureEdgeRelation`` already owns the canonical
12-value list at the app level, so a DB enum here would just be duplicate
ceremony for a value this codebase already validates elsewhere.

``confidence`` is ``1.0`` for a plain OpenAlex-sourced ``cites`` edge
(external fact, never a guess) and the classifier's own confidence for a
refined relation (``extends``/``improves``/etc.) -- never silently presented
with the same certainty as the underlying citation fact (research-integrity:
same "never silently promote a guess" rule as a detected-but-unconfirmed
``Repository``).

``openalex_work_id`` is the real OpenAlex work id this edge was grounded in
-- ``nullable=False`` so "an edge with no real external citation record
behind it" is a structural impossibility, not just a convention.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CitationEdge(Base):
    __tablename__ = "citation_edges"
    __table_args__ = (Index("ix_citation_edges_from_to", "from_paper_id", "to_paper_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    to_paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(32), nullable=False, default="cites")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    openalex_work_id: Mapped[str] = mapped_column(String(255), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
