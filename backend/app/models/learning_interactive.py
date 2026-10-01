"""A numeric-slider formula playground (docs/DATA_MODEL.md's ``LearningLayer``
/ Interactive). Gets its own table for the same reason as
``LearningQuizQuestion``/``LearningDerivation`` -- its shape (a parameter
list plus a formula) doesn't fit ``GeneratedSection``'s flat heading/body
shape.

``formula`` is NEVER evaluated with ``eval``/``exec``/``compile`` anywhere in
this codebase. It is validated at generation time
(``app.evidence.interactive.generate_interactives``) against the restricted
grammar in ``app.evidence.formula`` (SECURITY.md's "restricted declarative
grammar ... never eval, never arbitrary JS" requirement) before persistence,
and any future live-evaluation path must route through
``app.evidence.formula.evaluate_formula``, never Python's own eval.

``claim_ids`` is validated against the paper's persisted ``Claim`` rows
*before* a batch is ever added to the session, same discipline as
``LearningQuizQuestion.claim_ids``.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LearningInteractive(Base):
    __tablename__ = "learning_interactives"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # list[{"name": str, "label": str, "min": float, "max": float,
    #        "step": float, "default": float, "unit": str | None}] -- parsed
    # back into InteractiveParameterResponse by InteractiveResponse.
    parameters: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    # String(500) matches app.evidence.formula.MAX_FORMULA_LENGTH -- kept in
    # sync by a test asserting the two are equal, rather than a cross-layer
    # import (models/ never imports app.evidence/, same direction every
    # other model in this package already follows).
    formula: Mapped[str] = mapped_column(String(500), nullable=False)
    output_label: Mapped[str] = mapped_column(String(256), nullable=False)
    # list[str] (str(uuid)), not list[uuid.UUID] -- JSONB has no native UUID
    # element type, same as GeneratedSection.claim_ids.
    claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
