"""add structured address fields to properties

Revision ID: 0011_address
Revises: 0010_inactive
Create Date: 2026-05-19 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_address"
down_revision: Union[str, Sequence[str], None] = "0010_inactive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "properties", sa.Column("street", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "properties", sa.Column("city", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "properties", sa.Column("state", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "properties", sa.Column("country", sa.String(length=128), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("properties", "country")
    op.drop_column("properties", "state")
    op.drop_column("properties", "city")
    op.drop_column("properties", "street")
