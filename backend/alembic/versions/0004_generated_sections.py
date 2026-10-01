"""create generated_sections table

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-17

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# create_type=False, same reasoning as 0002/0003's enums: created and dropped
# explicitly, once, instead of implicitly by create_table.
generated_section_type_enum = postgresql.ENUM(
    "report", "technical", name="generated_section_type", create_type=False
)


def upgrade() -> None:
    generated_section_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "generated_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section_type", generated_section_type_enum, nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("claim_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_generated_sections_paper_id", "generated_sections", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_generated_sections_paper_id", table_name="generated_sections")
    op.drop_table("generated_sections")
    generated_section_type_enum.drop(op.get_bind(), checkfirst=True)
