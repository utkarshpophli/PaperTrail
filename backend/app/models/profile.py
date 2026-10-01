"""Recommendation-input profile (docs/DATA_MODEL.md's ``User``/``Profile``
entity: interests/level/goals). Not to be confused with ``app.models.user``'s
``User`` (Phase 0 login identity) -- this is the Phase 5 Discovery input,
one row per user.

Defaulted lazily: no row is created at registration time. ``PUT
/discover/profile`` upserts, and ``GET /discover/profile`` creates a default
row on first read if none exists yet (ARCHITECTURE.md's Phase 5 decisions --
"one row per user, upserted by PUT, defaulted lazily if none exists yet").
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    interests: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Plain string, not a DB enum -- validated at the request-schema boundary
    # (app.discovery.schemas.ProfileUpdateRequest's Literal) instead. Avoids
    # a Postgres ENUM type + migration churn for a value with no behavior
    # attached to it beyond input validation.
    level: Mapped[str] = mapped_column(String(32), nullable=False, default="beginner")
    goals: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
