"""add countered_amount column to bids (manager counter-offer rate)

Revision ID: 0029_bid_countered
Revises: 0028_invoice_email
Create Date: 2026-05-30 21:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0029_bid_countered"
down_revision: Union[str, Sequence[str], None] = "0028_invoice_email"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bids",
        sa.Column("countered_amount", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bids", "countered_amount")
