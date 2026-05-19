"""add property_day_prices table for per-night rate overrides

Revision ID: 0012_day_prices
Revises: 0011_address
Create Date: 2026-05-19 11:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_day_prices"
down_revision: Union[str, Sequence[str], None] = "0011_address"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "property_day_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("b2b_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("b2c_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "property_id", "date", name="uq_day_prices_property_date"
        ),
    )
    op.create_index(
        "ix_property_day_prices_property_id",
        "property_day_prices",
        ["property_id"],
    )
    op.create_index(
        "ix_property_day_prices_date", "property_day_prices", ["date"]
    )


def downgrade() -> None:
    op.drop_index("ix_property_day_prices_date", table_name="property_day_prices")
    op.drop_index(
        "ix_property_day_prices_property_id", table_name="property_day_prices"
    )
    op.drop_table("property_day_prices")
