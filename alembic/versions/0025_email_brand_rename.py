"""rename B2CAgent → B2C Tour Agent in seeded email templates

Revision ID: 0025_email_brand
Revises: 0024_email_html
Create Date: 2026-05-24 08:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0025_email_brand"
down_revision: Union[str, Sequence[str], None] = "0024_email_html"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD = "B2CAgent"
NEW = "B2C Tour Agent"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE email_templates "
            "SET subject = REPLACE(subject, :old, :new), "
            "    body = REPLACE(body, :old, :new), "
            "    updated_at = now() "
            "WHERE subject LIKE :pat OR body LIKE :pat"
        ).bindparams(old=OLD, new=NEW, pat=f"%{OLD}%")
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE email_templates "
            "SET subject = REPLACE(subject, :new, :old), "
            "    body = REPLACE(body, :new, :old), "
            "    updated_at = now() "
            "WHERE subject LIKE :pat OR body LIKE :pat"
        ).bindparams(old=OLD, new=NEW, pat=f"%{NEW}%")
    )
