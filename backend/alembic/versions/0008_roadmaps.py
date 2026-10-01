"""create roadmaps

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "roadmaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_description", sa.String(length=512), nullable=False),
        sa.Column(
            "target_paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("concepts", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("edges", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("milestones", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("overview", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_roadmaps_user_id", "roadmaps", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_roadmaps_user_id", table_name="roadmaps")
    op.drop_table("roadmaps")
