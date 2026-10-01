"""Story-level metadata for a paper's StorySpec (title, dek, reading time,
closing). The per-section visuals live on ``GeneratedSection.data`` -- this
table only holds what belongs to the story as a whole, one row per paper.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Story(Base):
    __tablename__ = "stories"
    __table_args__ = (UniqueConstraint("paper_id", name="uq_stories_paper_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    dek: Mapped[str] = mapped_column(Text, nullable=False)
    reading_time: Mapped[str] = mapped_column(String(64), nullable=False)
    # {"title": str, "body": str}
    closing: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
