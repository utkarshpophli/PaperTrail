"""Enrichment for a paper's extracted PDF figures: the parsed label, an
explanation of why the figure matters, and the claims it supports.

The figure *list* is owned by ``pages.figures`` (written by the document
parser); a row here only exists once the figure-linking pass has run, and a
figure with no row is still listed (unlinked).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Figure(Base):
    __tablename__ = "figures"
    __table_args__ = (UniqueConstraint("paper_id", "filename", name="uq_figures_paper_id_filename"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    why_it_matters: Mapped[str | None] = mapped_column(Text, nullable=True)
    # list[str] (str(uuid)) -- JSONB has no native UUID element type. Validated
    # against the paper's claims before persistence, same as GeneratedSection.
    claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
