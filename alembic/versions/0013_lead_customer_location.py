"""add customer stay location to leads

Revision ID: 0013_lead_loc
Revises: 0012_day_prices
Create Date: 2026-05-19 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_lead_loc"
down_revision: Union[str, Sequence[str], None] = "0012_day_prices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("customer_location_text", sa.String(length=512), nullable=True),
    )
    op.add_column("leads", sa.Column("customer_lat", sa.Float(), nullable=True))
    op.add_column("leads", sa.Column("customer_lng", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "customer_lng")
    op.drop_column("leads", "customer_lat")
    op.drop_column("leads", "customer_location_text")
