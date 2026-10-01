"""A claim extracted from a paper (docs/DATA_MODEL.md's ``Claim`` — the hub
node every downstream artifact links to).

``verification_status`` defaults to ``needs_review`` and is written only by
``app.evidence.verifier`` / ``app.evidence.service`` — no extraction code
path sets it directly (DATA_MODEL.md's "enforced, not just documented" rule).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, enum_values


class ClaimKind(str, enum.Enum):
    reported_result = "reported-result"
    author_interpretation = "author-interpretation"
    method = "method"
    background = "background"
    limitation = "limitation"


class VerificationStatus(str, enum.Enum):
    verified = "verified"
    partially_matched = "partially-matched"
    mismatch = "mismatch"
    not_found = "not-found"
    needs_review = "needs-review"


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement: Mapped[str] = mapped_column(String(4096), nullable=False)
    kind: Mapped[ClaimKind] = mapped_column(Enum(ClaimKind, name="claim_kind", values_callable=enum_values), nullable=False)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="verification_status", values_callable=enum_values),
        nullable=False,
        default=VerificationStatus.needs_review,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # lazy="selectin": async SQLAlchemy has no implicit lazy-load (no sync
    # I/O on attribute access), so every claim's source refs are eagerly
    # loaded in the same query set rather than requiring every caller to
    # remember `selectinload(Claim.source_refs)`.
    source_refs: Mapped[list["SourceReference"]] = relationship(  # noqa: F821
        back_populates="claim", cascade="all, delete-orphan", lazy="selectin"
    )
