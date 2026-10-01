"""create profiles and topic_landscapes

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interests", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("level", sa.String(length=32), nullable=False, server_default="beginner"),
        sa.Column("goals", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=True)

    op.create_table(
        "topic_landscapes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("topic", sa.String(length=512), nullable=False),
        sa.Column("overview", sa.Text(), nullable=False),
        sa.Column("papers", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("clusters", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_topic_landscapes_user_id", "topic_landscapes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_topic_landscapes_user_id", table_name="topic_landscapes")
    op.drop_table("topic_landscapes")
    op.drop_index("ix_profiles_user_id", table_name="profiles")
    op.drop_table("profiles")
