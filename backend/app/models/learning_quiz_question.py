"""A comprehension-check quiz question generated from a paper's claims
(docs/DATA_MODEL.md's ``LearningLayer`` / Quiz). Gets its own table (unlike
Story/Primer/ApplicationGuide, which reuse ``GeneratedSection``) because its
shape -- options, a correct answer, an explanation -- doesn't fit the
heading/body shape the other four content types share.

``claim_ids`` is validated against the paper's persisted ``Claim`` rows
*before* a batch is ever added to the session (``app.evidence.learning``),
same discipline as ``GeneratedSection.claim_ids``.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LearningQuizQuestion(Base):
    __tablename__ = "learning_quiz_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # None for a free-response/short-answer question; a list of choices for
    # multiple-choice -- the prompt/schema decides which shape a given
    # question takes, this column just stores whichever it was.
    options: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    correct_answer: Mapped[str] = mapped_column(String(1024), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    # list[str] (str(uuid)), not list[uuid.UUID] -- JSONB has no native UUID
    # element type, same as GeneratedSection.claim_ids.
    claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
