"""inbox: bid-thread messages + notifications

Revision ID: 0020_inbox
Revises: 0019_plan_limits
Create Date: 2026-05-23 21:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0020_inbox"
down_revision: Union[str, Sequence[str], None] = "0019_plan_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bid_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bid_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bids.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "sender_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), nullable=True
        ),
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
    )
    op.create_index(
        "ix_bid_messages_bid_created",
        "bid_messages",
        ["bid_id", "created_at"],
    )

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Free-form event code (e.g. bid_accepted, bid_placed, payment_initiated).
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        # Optional in-app link the UI can navigate to.
        sa.Column("link", sa.String(255), nullable=True),
        # Optional FK-ish ids for context (left as plain UUID to avoid coupling).
        sa.Column(
            "related_bid_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), nullable=True
        ),
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
    )
    op.create_index(
        "ix_notifications_user_created",
        "notifications",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_bid_messages_bid_created", table_name="bid_messages")
    op.drop_table("bid_messages")
