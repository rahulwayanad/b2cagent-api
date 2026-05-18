"""add 'inactive' value to property_status enum

Revision ID: 0010_inactive
Revises: 0009_draft
Create Date: 2026-05-17 11:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010_inactive"
down_revision: Union[str, Sequence[str], None] = "0009_draft"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE property_status ADD VALUE IF NOT EXISTS 'inactive'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE DROP VALUE.
    pass
