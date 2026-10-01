"""create learning_interactives

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_interactives",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("parameters", postgresql.JSONB, nullable=False, server_default="[]"),
        # length matches app.evidence.formula.MAX_FORMULA_LENGTH
        sa.Column("formula", sa.String(length=500), nullable=False),
        sa.Column("output_label", sa.String(length=256), nullable=False),
        sa.Column("claim_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_learning_interactives_paper_id", "learning_interactives", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_learning_interactives_paper_id", table_name="learning_interactives")
    op.drop_table("learning_interactives")
