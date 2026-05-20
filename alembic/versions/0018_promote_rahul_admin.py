"""promote existing rahulmeppadi@gmail.com user to super_admin

When 0017 ran the user already existed (with a different phone), so the seed
INSERT was skipped. This migration upgrades that row to admin and renames it
to 'Rahul'. Phone is intentionally left alone because '9048964143' is already
held by another user and reassigning it would break the unique index.

Revision ID: 0018_promote_rahul
Revises: 0017_subs_admin
Create Date: 2026-05-20 04:45:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0018_promote_rahul"
down_revision: Union[str, Sequence[str], None] = "0017_subs_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET full_name = 'Rahul',
            role = 'super_admin',
            active_role = 'super_admin',
            email_verified = true,
            is_active = true
        WHERE email = 'rahulmeppadi@gmail.com'
        """
    )


def downgrade() -> None:
    # Cannot recover prior name/role without an audit trail. One-way.
    pass
