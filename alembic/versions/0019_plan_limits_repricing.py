"""subscription_plans: add property + phone visibility limits, reprice tiers

Revision ID: 0019_plan_limits
Revises: 0018_promote_rahul_admin
Create Date: 2026-05-23 18:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0019_plan_limits"
down_revision: Union[str, Sequence[str], None] = "0018_promote_rahul"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscription_plans",
        sa.Column(
            "monthly_property_limit", sa.Integer(), nullable=True
        ),
    )
    op.add_column(
        "subscription_plans",
        sa.Column(
            "broker_phone_visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Reprice + set new limits per product spec (B2CAgent subscription rules).
    op.execute(
        """
        UPDATE subscription_plans
        SET price = 100, monthly_property_limit = 1, broker_phone_visible = false
        WHERE code = 'free'
        """
    )
    op.execute(
        """
        UPDATE subscription_plans
        SET price = 100, monthly_property_limit = 5, broker_phone_visible = true
        WHERE code = 'pro'
        """
    )
    op.execute(
        """
        UPDATE subscription_plans
        SET price = 250, monthly_property_limit = 10, broker_phone_visible = true
        WHERE code = 'pro_max'
        """
    )
    op.execute(
        """
        UPDATE subscription_plans
        SET price = 100, monthly_property_limit = 30, broker_phone_visible = true
        WHERE code = 'unlimited'
        """
    )


def downgrade() -> None:
    op.drop_column("subscription_plans", "broker_phone_visible")
    op.drop_column("subscription_plans", "monthly_property_limit")
    op.execute(
        """
        UPDATE subscription_plans SET price = 0 WHERE code = 'free';
        UPDATE subscription_plans SET price = 1000 WHERE code = 'unlimited';
        """
    )
