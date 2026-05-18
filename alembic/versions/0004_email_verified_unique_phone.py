"""add email_verified and unique constraint on phone

Revision ID: 0004_email_verified_unique_phone
Revises: 0003_nullable_google_sub
Create Date: 2026-05-15 00:00:01.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_email_verified_unique_phone"
down_revision: Union[str, Sequence[str], None] = "0003_nullable_google_sub"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("users", "email_verified", server_default=None)
    op.create_unique_constraint("uq_users_phone", "users", ["phone"])
    op.create_index("ix_users_phone", "users", ["phone"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_constraint("uq_users_phone", "users", type_="unique")
    op.drop_column("users", "email_verified")
