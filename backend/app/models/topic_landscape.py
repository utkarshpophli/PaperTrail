"""A saved topic-search result (docs/DATA_MODEL.md's ``TopicLandscape`` /
``MethodCluster``). ``papers``/``clusters`` are stored as JSONB on this one
row, not separate relational tables -- they are always read/written as a
whole landscape snapshot (never queried independently of their parent), so a
join-able child table would be speculative structure this project's
code-quality rule (no tables beyond what's needed) argues against.

No TTL/cleanup job for MVP (ARCHITECTURE.md's Phase 5 decisions) -- rows
persist indefinitely until that's a measured problem.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TopicLandscape(Base):
    __tablename__ = "topic_landscapes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(512), nullable=False)
    overview: Mapped[str] = mapped_column(Text, nullable=False)
    # list[dict] shape: app.discovery.schemas.LandscapePaperItem
    papers: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    # list[dict] shape: app.discovery.schemas.MethodClusterItem
    clusters: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
