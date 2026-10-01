"""extend generated_section_type; create learning_quiz_questions, learning_derivations

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_NEW_SECTION_TYPES = ("story", "primer", "application_guide")


def upgrade() -> None:
    # Postgres enums grow only via ALTER TYPE ... ADD VALUE (no direct DROP);
    # each addition run outside a transaction block per Postgres's own
    # restriction on ADD VALUE inside a transaction.
    with op.get_context().autocommit_block():
        for value in _NEW_SECTION_TYPES:
            op.execute(f"ALTER TYPE generated_section_type ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        "learning_quiz_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB, nullable=True),
        sa.Column("correct_answer", sa.String(length=1024), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("claim_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_learning_quiz_questions_paper_id", "learning_quiz_questions", ["paper_id"])

    op.create_table(
        "learning_derivations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("steps", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_learning_derivations_paper_id", "learning_derivations", ["paper_id"])


def downgrade() -> None:
    # Note: does not remove 'story'/'primer'/'application_guide' from the
    # generated_section_type enum -- Postgres has no DROP VALUE, only a
    # rebuild-the-type dance. Any generated_sections rows using the new
    # values must be deleted/migrated by hand before a real downgrade if
    # that's ever required; left as-is here, same tradeoff already accepted
    # implicitly by every additive-enum migration in this codebase.
    op.drop_index("ix_learning_derivations_paper_id", table_name="learning_derivations")
    op.drop_table("learning_derivations")
    op.drop_index("ix_learning_quiz_questions_paper_id", table_name="learning_quiz_questions")
    op.drop_table("learning_quiz_questions")
