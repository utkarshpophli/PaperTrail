"""create evidence, claims, source_references, metrics, glossary_terms tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-17

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# create_type=False, same reasoning as 0002's parse_status_enum: created and
# dropped explicitly, once, instead of implicitly by create_table.
claim_kind_enum = postgresql.ENUM(
    "reported-result", "author-interpretation", "method", "background", "limitation",
    name="claim_kind", create_type=False,
)
verification_status_enum = postgresql.ENUM(
    "verified", "partially-matched", "mismatch", "not-found", "needs-review",
    name="verification_status", create_type=False,
)


def upgrade() -> None:
    claim_kind_enum.create(op.get_bind(), checkfirst=True)
    verification_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("plain_summary", sa.Text(), nullable=False),
        sa.Column("research_question", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("statement", sa.String(length=4096), nullable=False),
        sa.Column("kind", claim_kind_enum, nullable=False),
        sa.Column(
            "verification_status", verification_status_enum, nullable=False, server_default="needs-review"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_claims_paper_id", "claims", ["paper_id"])

    op.create_table(
        "source_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("locator", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_source_references_claim_id", "source_references", ["claim_id"])

    op.create_table(
        "metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("display_value", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("context", sa.String(length=1024), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("source_excerpt", sa.Text(), nullable=False),
    )
    op.create_index("ix_metrics_paper_id", "metrics", ["paper_id"])

    op.create_table(
        "glossary_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String(length=255), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
    )
    op.create_index("ix_glossary_terms_paper_id", "glossary_terms", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_glossary_terms_paper_id", table_name="glossary_terms")
    op.drop_table("glossary_terms")
    op.drop_index("ix_metrics_paper_id", table_name="metrics")
    op.drop_table("metrics")
    op.drop_index("ix_source_references_claim_id", table_name="source_references")
    op.drop_table("source_references")
    op.drop_index("ix_claims_paper_id", table_name="claims")
    op.drop_table("claims")
    op.drop_table("evidence")
    verification_status_enum.drop(op.get_bind(), checkfirst=True)
    claim_kind_enum.drop(op.get_bind(), checkfirst=True)
