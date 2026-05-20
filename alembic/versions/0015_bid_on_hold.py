"""add on_hold bid status

Revision ID: 0015_bid_on_hold
Revises: 0014_bid_payments
Create Date: 2026-05-19 18:30:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0015_bid_on_hold"
down_revision: Union[str, Sequence[str], None] = "0014_bid_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ADD VALUE cannot run inside a transaction block in older
    # Postgres releases. Use COMMIT/BEGIN to step outside; works in 12+
    # for either path, and is safe to re-run thanks to IF NOT EXISTS.
    op.execute("COMMIT")
    op.execute("ALTER TYPE bid_status ADD VALUE IF NOT EXISTS 'on_hold'")


def downgrade() -> None:
    # Postgres doesn't support removing an enum value without rebuilding the
    # type. Treat this as one-way.
    pass
