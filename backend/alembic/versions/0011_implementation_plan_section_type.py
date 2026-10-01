"""extend generated_section_type with implementation_plan

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-18

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Postgres enums grow only via ALTER TYPE ... ADD VALUE (no direct DROP);
    # run outside a transaction block per Postgres's own restriction on ADD
    # VALUE inside a transaction -- same pattern as 0005's extension of this
    # same enum for story/primer/application_guide.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE generated_section_type ADD VALUE IF NOT EXISTS 'implementation_plan'")


def downgrade() -> None:
    # Note: does not remove 'implementation_plan' from the enum -- Postgres
    # has no DROP VALUE, only a rebuild-the-type dance. Any generated_sections
    # rows using this value must be deleted/migrated by hand before a real
    # downgrade if that's ever required; same tradeoff already accepted by
    # 0005's downgrade for the same enum.
    pass
