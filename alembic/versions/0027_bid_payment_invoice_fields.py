"""add invoice metadata to bid_payments (invoice_no, address snapshot, channels)

Revision ID: 0027_bid_payment_invoice
Revises: 0026_email_links
Create Date: 2026-05-24 23:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0027_bid_payment_invoice"
down_revision: Union[str, Sequence[str], None] = "0026_email_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bid_payments",
        sa.Column("invoice_no", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "bid_payments",
        sa.Column(
            "invoice_address_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "bid_payments",
        sa.Column("delivery_channels", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_bid_payments_invoice_no", "bid_payments", ["invoice_no"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_bid_payments_invoice_no", "bid_payments", type_="unique"
    )
    op.drop_column("bid_payments", "delivery_channels")
    op.drop_column("bid_payments", "invoice_address_json")
    op.drop_column("bid_payments", "invoice_no")
