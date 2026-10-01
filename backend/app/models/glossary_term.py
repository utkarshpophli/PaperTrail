"""A defined term for the paper's glossary (docs/DATA_MODEL.md's
``GlossaryTerm``).

``source_page``/``source_excerpt`` are nullable: a glossary definition may be
a general, non-sourced explanation of a term the paper uses but never itself
defines (e.g. "transformer"). The extraction prompt requires such
illustrative definitions to say so in the ``definition`` text itself
(AI_PROVIDERS.md's "illustrative values must be explicitly labeled") —
nullability here is what makes "no source for this one" representable at
all, rather than forcing a fabricated page/excerpt to satisfy a NOT NULL
column.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
