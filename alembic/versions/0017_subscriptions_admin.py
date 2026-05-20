"""subscription plans + admin seed + bid.accepted_at

Revision ID: 0017_subs_admin
Revises: 0016_cleanup_orphan
Create Date: 2026-05-20 04:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_subs_admin"
down_revision: Union[str, Sequence[str], None] = "0016_cleanup_orphan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- bid.accepted_at -------------------------------------------------
    op.add_column(
        "bids",
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Back-fill historical accepts with updated_at as a best guess so
    # existing managers don't bypass the quota retroactively.
    op.execute(
        "UPDATE bids SET accepted_at = updated_at WHERE status = 'accepted'"
    )

    # ---- subscription_plans ---------------------------------------------
    op.create_table(
        "subscription_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("monthly_bid_limit", sa.Integer(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        "ix_subscription_plans_code", "subscription_plans", ["code"]
    )

    # ---- user_subscriptions ---------------------------------------------
    op.create_table(
        "user_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "starts_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True
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
        sa.UniqueConstraint(
            "user_id", name="uq_user_subscriptions_user_id"
        ),
    )
    op.create_index(
        "ix_user_subscriptions_user_id", "user_subscriptions", ["user_id"]
    )
    op.create_index(
        "ix_user_subscriptions_plan_id", "user_subscriptions", ["plan_id"]
    )

    # ---- seed the four canonical plans ----------------------------------
    op.execute(
        """
        INSERT INTO subscription_plans (id, code, name, monthly_bid_limit, price, is_active, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'free', 'Free', 10, 0, true, now(), now()),
            (gen_random_uuid(), 'pro', 'Pro', 100, 100, true, now(), now()),
            (gen_random_uuid(), 'pro_max', 'Pro Max', 250, 250, true, now(), now()),
            (gen_random_uuid(), 'unlimited', 'Unlimited', NULL, 1000, true, now(), now())
        """
    )

    # ---- seed the founding admin user ----------------------------------
    # Idempotent: skip if a user with this email already exists.
    op.execute(
        """
        INSERT INTO users (
            id, email, full_name, role, active_role,
            phone, phone_verified, email_verified, is_active,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            'rahulmeppadi@gmail.com', 'Rahul',
            'super_admin', 'super_admin',
            '9048964143', true, true, true,
            now(), now()
        WHERE NOT EXISTS (
            SELECT 1 FROM users WHERE email = 'rahulmeppadi@gmail.com'
        )
        """
    )

    # ---- give the admin an Unlimited plan ------------------------------
    op.execute(
        """
        INSERT INTO user_subscriptions (id, user_id, plan_id, starts_at, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            u.id,
            p.id,
            now(),
            now(),
            now()
        FROM users u, subscription_plans p
        WHERE u.email = 'rahulmeppadi@gmail.com'
          AND p.code = 'unlimited'
          AND NOT EXISTS (
              SELECT 1 FROM user_subscriptions us WHERE us.user_id = u.id
          )
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_subscriptions_plan_id", table_name="user_subscriptions"
    )
    op.drop_index(
        "ix_user_subscriptions_user_id", table_name="user_subscriptions"
    )
    op.drop_table("user_subscriptions")
    op.drop_index(
        "ix_subscription_plans_code", table_name="subscription_plans"
    )
    op.drop_table("subscription_plans")
    op.drop_column("bids", "accepted_at")
