"""users.avatar_url

Revision ID: 0022_user_avatar
Revises: 0021_notif_audience
Create Date: 2026-05-24 00:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0022_user_avatar"
down_revision: Union[str, Sequence[str], None] = "0021_notif_audience"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_url", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
