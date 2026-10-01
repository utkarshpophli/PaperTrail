"""A generated, persisted research roadmap snapshot (docs/DATA_MODEL.md's
Phase 6 entities; ARCHITECTURE.md's Phase 6 decisions).

Same JSONB-snapshot persistence idiom as ``TopicLandscape``: ``concepts``/
``edges``/``milestones`` are always read/written as a whole roadmap, never
queried piecemeal, so there are no separate relational tables for them.
Per-user milestone progress (``status`` on each milestone dict) lives inside
this same row rather than a separate progress table, since a roadmap here is
generated per-user (not a shared curated path multiple users follow).

``target_paper_id`` is ``SET NULL`` (not ``CASCADE``) on paper deletion --
losing the anchor paper shouldn't delete the roadmap snapshot itself, since
the roadmap's concepts/milestones are already-persisted, self-contained JSONB
data that doesn't require the source row to still exist to remain readable.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Roadmap(Base):
    __tablename__ = "roadmaps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_description: Mapped[str] = mapped_column(String(512), nullable=False)
    target_paper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="SET NULL"), nullable=True
    )
    # list[dict] shape: app.discovery.schemas.Concept
    concepts: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    # list[dict] shape: app.discovery.schemas.PrerequisiteEdge
    edges: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    # list[dict] shape: app.discovery.schemas.Milestone
    milestones: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    overview: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
