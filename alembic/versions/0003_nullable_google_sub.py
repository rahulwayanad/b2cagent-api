"""make google_sub nullable for email/phone-only users

Revision ID: 0003_nullable_google_sub
Revises: 0002_property_types
Create Date: 2026-05-15 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_nullable_google_sub"
down_revision: Union[str, Sequence[str], None] = "0002_property_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "google_sub",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE users SET google_sub = '' WHERE google_sub IS NULL")
    op.alter_column(
        "users",
        "google_sub",
        existing_type=sa.String(length=255),
        nullable=False,
    )
