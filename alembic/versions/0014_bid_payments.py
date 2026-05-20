"""bid payments: gate booking creation behind cash/online payment confirmation

Revision ID: 0014_bid_payments
Revises: 0013_lead_loc
Create Date: 2026-05-19 16:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_bid_payments"
down_revision: Union[str, Sequence[str], None] = "0013_lead_loc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enums via raw SQL with IF NOT EXISTS semantics so partial reruns
    # are safe. asyncpg + SQLAlchemy's Enum.create(checkfirst=True) has
    # repeatedly tried to CREATE TYPE a second time inside the table-create
    # transaction; using DO blocks avoids that path.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_method') THEN
                CREATE TYPE payment_method AS ENUM ('cash', 'online');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_status') THEN
                CREATE TYPE payment_status AS ENUM ('initiated', 'confirmed');
            END IF;
        END
        $$;
        """
    )

    op.create_table(
        "bid_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bid_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bids.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "method",
            postgresql.ENUM(
                "cash", "online", name="payment_method", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "initiated",
                "confirmed",
                name="payment_status",
                create_type=False,
            ),
            nullable=False,
            server_default="initiated",
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "confirmed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("bid_id", name="uq_bid_payments_bid_id"),
    )
    op.create_index("ix_bid_payments_bid_id", "bid_payments", ["bid_id"])


def downgrade() -> None:
    op.drop_index("ix_bid_payments_bid_id", table_name="bid_payments")
    op.drop_table("bid_payments")
    op.execute("DROP TYPE IF EXISTS payment_status")
    op.execute("DROP TYPE IF EXISTS payment_method")
