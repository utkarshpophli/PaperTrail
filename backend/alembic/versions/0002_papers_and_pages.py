"""create papers and pages tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# create_type=False: the enum is created/dropped explicitly below, once,
# instead of implicitly by create_table — avoids a DuplicateObjectError from
# create_table trying to create it again after our explicit create() call.
parse_status_enum = postgresql.ENUM(
    "pending", "parsing", "parsed", "failed", name="parse_status", create_type=False
)


def upgrade() -> None:
    parse_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "papers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("authors", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("venue", sa.String(length=512), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("arxiv_id", sa.String(length=64), nullable=True),
        sa.Column("source_file_path", sa.String(length=1024), nullable=False),
        sa.Column("parse_status", parse_status_enum, nullable=False, server_default="pending"),
        sa.Column("parse_error", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_papers_user_id", "papers", ["user_id"])

    op.create_table(
        "pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("figures", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.UniqueConstraint("paper_id", "page_number", name="uq_pages_paper_id_page_number"),
    )
    op.create_index("ix_pages_paper_id", "pages", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_pages_paper_id", table_name="pages")
    op.drop_table("pages")
    op.drop_index("ix_papers_user_id", table_name="papers")
    op.drop_table("papers")
    parse_status_enum.drop(op.get_bind(), checkfirst=True)
