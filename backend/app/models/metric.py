"""A numeric/reported result pulled out of a paper for the metrics table
(docs/DATA_MODEL.md's ``Metric``).

``value``/``display_value`` are both strings, not a float column: papers
report metrics in forms that don't reduce cleanly to one numeric type
("87.3", "13 layers", "O(n log n)") — ``value`` keeps the raw token as
reported, ``display_value`` is the human-facing formatted form (e.g. with a
``%``/unit appended). Forcing a float column would either reject legitimate
non-numeric metrics or silently drop precision/formatting.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    display_value: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_page: Mapped[int] = mapped_column(Integer, nullable=False)
    source_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
