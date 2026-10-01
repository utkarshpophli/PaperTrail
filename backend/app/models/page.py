"""One row per parsed page of a Paper (docs/DATA_MODEL.md's
``ParsedDocument.pages``)."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("paper_id", "page_number", name="uq_pages_paper_id_page_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    figures: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
