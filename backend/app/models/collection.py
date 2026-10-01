"""A user-curated list of papers (docs/DATA_MODEL.md's ``Collection``).

``paper_ids`` is a JSONB list of UUID strings, not a join table -- a
collection's paper list is small and always read/written as a whole, same
"don't add a relational table for something read as one blob" call already
made for ``TopicLandscape.papers``/``Roadmap.milestones`` (ARCHITECTURE.md's
Phase 7 decisions).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # list[str] of Paper UUIDs (as strings) -- never a bare arxiv_id or any
    # other identifier, matching this field's convention everywhere else in
    # the schema (see app.discovery.service.promote_landscape).
    paper_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
