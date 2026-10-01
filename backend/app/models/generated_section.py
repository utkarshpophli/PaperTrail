"""Claim-linked derived report/technical-appendix/story/primer/application-guide
sections (docs/DATA_MODEL.md's ``DeepReportSection``/``TechnicalAppendix``/
``StorySection``/``LearningLayer`` Primer & ApplicationGuide). One shared
storage shape per this phase's design decision #1 -- only the prompts/
generation logic differ across ``app.evidence.report``/``technical``/
``story``/``learning``; the row shape below is common to all five, distinguished
by ``section_type``. Quiz and Derivation (the other two Learning Layer content
types) get their own tables (``LearningQuizQuestion``/``LearningDerivation``)
because their shapes don't fit this flat heading/body pattern.

``title``/``content`` (rather than the ``heading``/``body`` names sketched in
this phase's task brief) match ``app.evidence.schemas.GeneratedSectionResponse``,
which ``backend-engineer`` had already defined with those names by the time
this model was written -- kept in sync with that existing contract rather
than the brief's literal field list. See this phase's handback report.

``claim_ids`` is validated against the paper's persisted ``Claim`` rows
*before* a batch of sections is ever added to the session
(``app.evidence.report``/``app.evidence.technical``) -- never enforced at the
DB level alone, since Postgres can't express "is a member of this paper's own
claim set" as a column constraint.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SectionType(str, enum.Enum):
    report = "report"
    technical = "technical"
    story = "story"
    primer = "primer"
    application_guide = "application_guide"
    implementation_plan = "implementation_plan"


class GeneratedSection(Base):
    __tablename__ = "generated_sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_type: Mapped[SectionType] = mapped_column(
        Enum(SectionType, name="generated_section_type"), nullable=False
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # list[str] (str(uuid)), not list[uuid.UUID] -- JSONB has no native UUID
    # element type. Parsed back to uuid.UUID by GeneratedSectionResponse.
    claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Type-specific payload. Story sections carry {kicker, index_label, visual};
    # every other section type leaves it NULL.
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
