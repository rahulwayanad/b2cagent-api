"""add 'both' to user_role enum and active_role column

Revision ID: 0006_dual_role
Revises: 0005_user_default_location
Create Date: 2026-05-16 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_dual_role"
down_revision: Union[str, Sequence[str], None] = "0005_user_default_location"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'both'")
    op.add_column(
        "users",
        sa.Column(
            "active_role",
            postgresql.ENUM(
                "agent",
                "manager",
                "super_admin",
                "both",
                name="user_role",
                create_type=False,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "active_role")
    # Postgres has no ALTER TYPE DROP VALUE — leaving 'both' in the enum on downgrade.
