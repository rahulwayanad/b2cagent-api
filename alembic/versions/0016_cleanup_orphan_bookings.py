"""delete orphan bookings whose bid has no confirmed payment

The old accept-bid flow created Booking rows at the moment the manager hit
Accept. Payment-gating moved to confirm_bid_payment in 0014, but legacy rows
that were created before that change remain in the table, which makes the
lead detail page render a "Booking confirmed" card for bids that the agent
hasn't even paid for yet.

This migration deletes those leftover rows. Going forward, only
confirm_bid_payment can create bookings, so the data stays consistent.

Revision ID: 0016_cleanup_orphan
Revises: 0015_bid_on_hold
Create Date: 2026-05-20 04:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0016_cleanup_orphan"
down_revision: Union[str, Sequence[str], None] = "0015_bid_on_hold"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM bookings
        WHERE bid_id IS NOT NULL
          AND bid_id NOT IN (
              SELECT bid_id FROM bid_payments
              WHERE status = 'confirmed' AND bid_id IS NOT NULL
          )
        """
    )


def downgrade() -> None:
    # Deleted rows cannot be reconstructed. One-way cleanup.
    pass
