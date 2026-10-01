"""create code_links

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Reuses the enum type created in 0003 -- a second type would let a code
# link's status drift from the claim verification vocabulary.
verification_status_enum = postgresql.ENUM(
    "verified", "partially-matched", "mismatch", "not-found", "needs-review",
    name="verification_status", create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "code_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("verification_status", verification_status_enum, nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("end_line >= start_line", name="ck_code_links_line_order"),
    )
    op.create_index("ix_code_links_user_id", "code_links", ["user_id"])
    op.create_index("ix_code_links_paper_id", "code_links", ["paper_id"])
    op.create_index("ix_code_links_repository_claim", "code_links", ["repository_id", "claim_id"])


def downgrade() -> None:
    op.drop_index("ix_code_links_repository_claim", table_name="code_links")
    op.drop_index("ix_code_links_paper_id", table_name="code_links")
    op.drop_index("ix_code_links_user_id", table_name="code_links")
    op.drop_table("code_links")
