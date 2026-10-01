"""Per-paper narrative summary (docs/DATA_MODEL.md's ``Evidence``).

Unlike ``Claim``, ``thesis``/``plain_summary``/``research_question`` carry no
``source_refs`` of their own in the data model — they're a narrative reading
of the whole paper, not individually-cited statements. Claim-level grounding
still applies everywhere else in the graph.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    plain_summary: Mapped[str] = mapped_column(Text, nullable=False)
    research_question: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
