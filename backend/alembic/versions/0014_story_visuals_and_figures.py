"""generated_sections.data; create stories, figures

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generated_sections", sa.Column("data", postgresql.JSONB, nullable=True))

    op.create_table(
        "stories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("dek", sa.Text(), nullable=False),
        sa.Column("reading_time", sa.String(length=64), nullable=False),
        sa.Column("closing", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("paper_id", name="uq_stories_paper_id"),
    )

    op.create_table(
        "figures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("claim_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("paper_id", "filename", name="uq_figures_paper_id_filename"),
    )
    op.create_index("ix_figures_paper_id", "figures", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_figures_paper_id", table_name="figures")
    op.drop_table("figures")
    op.drop_table("stories")
    op.drop_column("generated_sections", "data")
