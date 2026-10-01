"""A claim's evidence pointer: page + verbatim excerpt (docs/DATA_MODEL.md's
``SourceReference``). ``excerpt`` is non-null — a claim is never persisted
with a source reference that has no quote to verify against (enforced
alongside the "at least one source_ref per claim" rule in
``app.evidence.service``).
"""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SourceReference(Base):
    __tablename__ = "source_references"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[str | None] = mapped_column(String(255), nullable=True)

    claim: Mapped["Claim"] = relationship(back_populates="source_refs")  # noqa: F821
