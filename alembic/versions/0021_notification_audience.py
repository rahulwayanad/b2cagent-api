"""notifications.audience_role: which role view should see this notification

Revision ID: 0021_notif_audience
Revises: 0020_inbox
Create Date: 2026-05-23 22:45:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0021_notif_audience"
down_revision: Union[str, Sequence[str], None] = "0020_inbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("audience_role", sa.String(16), nullable=True),
    )
    # Legacy rows (created before this column existed) stay NULL on purpose —
    # they're treated as audience-agnostic and show up in every role's inbox,
    # same as the "All" view. New writes set audience_role explicitly.


def downgrade() -> None:
    op.drop_column("notifications", "audience_role")
