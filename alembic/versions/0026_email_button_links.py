"""point email CTA buttons at real {link_url} instead of href="#"

Revision ID: 0026_email_links
Revises: 0025_email_brand
Create Date: 2026-05-24 08:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0026_email_links"
down_revision: Union[str, Sequence[str], None] = "0025_email_brand"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_HREF = 'href="#"'
NEW_HREF = 'href="{link_url}"'


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE email_templates "
            "SET body = REPLACE(body, :old, :new), "
            "    updated_at = now() "
            "WHERE body LIKE :pat"
        ).bindparams(old=OLD_HREF, new=NEW_HREF, pat=f"%{OLD_HREF}%")
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE email_templates "
            "SET body = REPLACE(body, :new, :old), "
            "    updated_at = now() "
            "WHERE body LIKE :pat"
        ).bindparams(old=OLD_HREF, new=NEW_HREF, pat=f"%{NEW_HREF}%")
    )
