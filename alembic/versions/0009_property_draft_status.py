"""add 'draft' value to property_status enum

Revision ID: 0009_draft
Revises: 0008_bookings
Create Date: 2026-05-17 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009_draft"
down_revision: Union[str, Sequence[str], None] = "0008_bookings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE property_status ADD VALUE IF NOT EXISTS 'draft'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE DROP VALUE.
    pass
