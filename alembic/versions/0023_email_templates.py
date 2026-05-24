"""email_templates master table

Revision ID: 0023_email_templates
Revises: 0022_user_avatar
Create Date: 2026-05-24 01:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0023_email_templates"
down_revision: Union[str, Sequence[str], None] = "0022_user_avatar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEEDS = [
    (
        "otp",
        "OTP code",
        "Your B2CAgent verification code",
        (
            "Hi {name},\n\n"
            "Your verification code is {otp}. It's valid for 5 minutes.\n\n"
            "If you didn't request this, you can safely ignore the email.\n\n"
            "— B2CAgent"
        ),
        "Sent every time we email a one-time code. {name}, {otp}",
    ),
    (
        "welcome",
        "Welcome",
        "Welcome to B2CAgent, {name}",
        (
            "Hi {name},\n\n"
            "Your B2CAgent account is now active as a {role}. "
            "Sign in to start {role_action}.\n\n"
            "— The B2CAgent team"
        ),
        "Sent right after signup is verified. {name}, {role}, {role_action}",
    ),
    (
        "bid_placed_agent",
        "Bid placed (agent)",
        "Bid placed for {property_name}",
        (
            "Hi {agent_name},\n\n"
            "We've recorded your bid of {amount}/night on {property_name} "
            "for {check_in} → {check_out}. We'll notify you the moment the "
            "property manager responds.\n\n"
            "— B2CAgent"
        ),
        "Confirmation to the agent. {agent_name}, {amount}, {property_name}, {check_in}, {check_out}",
    ),
    (
        "bid_placed_manager",
        "New bid (manager)",
        "New bid on {property_name}",
        (
            "Hi {manager_name},\n\n"
            "{agent_name} placed a bid of {amount}/night on {property_name} "
            "for {check_in} → {check_out}. Review it in B2CAgent.\n\n"
            "— B2CAgent"
        ),
        "Notifies the manager. {manager_name}, {agent_name}, {amount}, {property_name}, {check_in}, {check_out}",
    ),
    (
        "bid_accepted",
        "Bid accepted",
        "Your bid for {property_name} was accepted",
        (
            "Hi {agent_name},\n\n"
            "Great news — your bid of {amount}/night for {property_name} "
            "({check_in} → {check_out}) was accepted. Collect payment from "
            "your customer to confirm the booking.\n\n"
            "— B2CAgent"
        ),
        "Sent to the agent. {agent_name}, {amount}, {property_name}",
    ),
    (
        "bid_rejected",
        "Bid declined",
        "Your bid for {property_name} was declined",
        (
            "Hi {agent_name},\n\n"
            "Your bid for {property_name} ({check_in} → {check_out}) was "
            "declined. Try a different property — your customer is still active.\n\n"
            "— B2CAgent"
        ),
        "Sent to the agent. {agent_name}, {property_name}",
    ),
    (
        "bid_held",
        "Bid on hold",
        "Your bid for {property_name} is on hold",
        (
            "Hi {agent_name},\n\n"
            "Your bid on {property_name} is on hold — another bid was "
            "accepted for overlapping dates. We'll reactivate yours if the "
            "other one falls through.\n\n"
            "— B2CAgent"
        ),
        "Sent to the agent. {agent_name}, {property_name}",
    ),
    (
        "bid_withdrawn",
        "Bid withdrawn",
        "Bid withdrawn for {property_name}",
        (
            "Hi {manager_name},\n\n"
            "{agent_name} has withdrawn their bid for {property_name} "
            "({check_in} → {check_out}).\n\n"
            "— B2CAgent"
        ),
        "Sent to the manager. {manager_name}, {agent_name}, {property_name}",
    ),
    (
        "booking_confirmed",
        "Booking confirmed (agent)",
        "Booking confirmed for {property_name}",
        (
            "Hi {agent_name},\n\n"
            "Payment confirmed and the booking for {property_name} "
            "({check_in} → {check_out}) is locked in. You'll find the full "
            "details in your B2CAgent dashboard.\n\n"
            "— B2CAgent"
        ),
        "Sent to the agent only. {agent_name}, {property_name}, {check_in}, {check_out}",
    ),
    (
        "profile_updated",
        "Profile updated",
        "Your B2CAgent profile was updated",
        (
            "Hi {name},\n\n"
            "We noticed changes to your profile just now. If this wasn't you, "
            "secure your account by signing out everywhere from your profile page.\n\n"
            "— B2CAgent"
        ),
        "Sent when the user updates personal info. {name}",
    ),
    (
        "subscription_limit_warning",
        "Subscription nearing limit",
        "You're close to your {plan_name} limit",
        (
            "Hi {name},\n\n"
            "You've used {used} of {limit} {basis} this month on the "
            "{plan_name} plan. Upgrade now to keep things moving without "
            "interruption.\n\n"
            "— B2CAgent"
        ),
        "Triggered at ≥80% quota. {name}, {plan_name}, {used}, {limit}, {basis}",
    ),
    (
        "subscription_upgraded",
        "Plan upgraded",
        "You're now on the {plan_name} plan",
        (
            "Hi {name},\n\n"
            "Your subscription is now {plan_name}. You're set with "
            "{bid_limit} bids/month and {property_limit} properties.\n\n"
            "— B2CAgent"
        ),
        "Triggered when admin assigns a new plan. {name}, {plan_name}, {bid_limit}, {property_limit}",
    ),
]


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        "ix_email_templates_code", "email_templates", ["code"]
    )

    # Seed canonical templates.
    for code, name, subject, body, description in SEEDS:
        op.execute(
            sa.text(
                """
                INSERT INTO email_templates
                    (id, code, name, subject, body, description, is_active, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :code, :name, :subject, :body, :description, true, now(), now())
                """
            ).bindparams(
                code=code,
                name=name,
                subject=subject,
                body=body,
                description=description,
            )
        )


def downgrade() -> None:
    op.drop_index("ix_email_templates_code", table_name="email_templates")
    op.drop_table("email_templates")
