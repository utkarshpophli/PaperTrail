"""A stepped walkthrough of a key equation/result from a paper's method
(docs/DATA_MODEL.md's ``LearningLayer`` / Derivation). Gets its own table for
the same reason as ``LearningQuizQuestion`` -- a nested step list doesn't fit
``GeneratedSection``'s flat heading/body shape.

Each step's ``formula`` is **inert display text** (e.g. rendered math
notation as a string) -- it is never evaluated, never passed through any
expression parser. Live formula evaluation is the Interactive content type,
explicitly deferred to a later phase with its own security review.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LearningDerivation(Base):
    __tablename__ = "learning_derivations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # list[{"explanation": str, "formula": str, "claim_ids": list[str]}] --
    # each step's own claim_ids (str(uuid), JSONB has no native UUID element
    # type), parsed back to uuid.UUID by DerivationStepResponse.
    steps: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
