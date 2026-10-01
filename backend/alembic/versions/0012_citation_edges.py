"""create citation_edges

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "citation_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation", sa.String(length=32), nullable=False, server_default="cites"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("openalex_work_id", sa.String(length=255), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_citation_edges_user_id", "citation_edges", ["user_id"])
    op.create_index("ix_citation_edges_from_to", "citation_edges", ["from_paper_id", "to_paper_id"])


def downgrade() -> None:
    op.drop_index("ix_citation_edges_from_to", table_name="citation_edges")
    op.drop_index("ix_citation_edges_user_id", table_name="citation_edges")
    op.drop_table("citation_edges")
