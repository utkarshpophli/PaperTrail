"""A GitHub repository linked to a paper, either by the user directly or
surfaced as an unverified candidate by ``app.coderesearch``'s detection
route (docs/ARCHITECTURE.md's Code Research (Phase 8) section).

``confidence`` is ``None`` for ``source="user_linked"`` (a user's own link
is a fact, not a guess) and set for ``source="detected"`` -- this column
split, not just a shared "trust me" flag, is what keeps a detected repo
visibly distinct from a confirmed one at the schema level (research
integrity: a detected repo must never be silently promoted to the same
status as a user-confirmed link).
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

RepositorySource = Literal["user_linked", "detected"]


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Plain string column (not a SQLAlchemy Enum) -- unlike SectionType/
    # ParseStatus, this has exactly two literal values with no independent
    # lifecycle of their own, and no other table/enum reuses it. A DB-level
    # Enum type here would be the "config for a value that never changes"
    # kind of ceremony this codebase avoids elsewhere for two-value fields.
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
