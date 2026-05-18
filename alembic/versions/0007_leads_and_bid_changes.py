"""leads + lead_property_matches; restructure bids around leads

Revision ID: 0007_leads
Revises: 0006_dual_role
Create Date: 2026-05-17 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_leads"
down_revision: Union[str, Sequence[str], None] = "0006_dual_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    lead_status = sa.Enum(
        "draft", "active", "won", "lost", "expired", name="lead_status"
    )
    lead_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customer_name", sa.String(200), nullable=False),
        sa.Column("customer_email", sa.String(200), nullable=True),
        sa.Column("customer_phone", sa.String(20), nullable=True),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.Column(
            "is_single_day", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("adults", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("children", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("budget_min", sa.Numeric(10, 2), nullable=True),
        sa.Column("budget_max", sa.Numeric(10, 2), nullable=True),
        sa.Column("special_requirements", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "active", "won", "lost", "expired",
                name="lead_status", create_type=False,
            ),
            nullable=False,
            server_default="draft",
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
    op.create_index("ix_leads_agent_id", "leads", ["agent_id"])

    op.create_table(
        "lead_property_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("match_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "matched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "is_hidden", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.UniqueConstraint("lead_id", "property_id", name="uq_lead_property_match"),
    )
    op.create_index(
        "ix_lpm_lead_id", "lead_property_matches", ["lead_id"]
    )
    op.create_index(
        "ix_lpm_property_id", "lead_property_matches", ["property_id"]
    )

    # Drop existing bids — dev only — and reshape the table.
    op.execute("DELETE FROM bids")
    op.drop_constraint("uq_bids_property_agent_date", "bids", type_="unique")
    op.drop_column("bids", "bid_date")
    op.add_column(
        "bids",
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.add_column("bids", sa.Column("check_in", sa.Date(), nullable=False))
    op.add_column("bids", sa.Column("check_out", sa.Date(), nullable=False))
    op.create_index("ix_bids_lead_id", "bids", ["lead_id"])
    op.create_unique_constraint(
        "uq_bids_lead_property", "bids", ["lead_id", "property_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_bids_lead_property", "bids", type_="unique")
    op.drop_index("ix_bids_lead_id", table_name="bids")
    op.drop_column("bids", "check_out")
    op.drop_column("bids", "check_in")
    op.drop_column("bids", "lead_id")
    op.add_column("bids", sa.Column("bid_date", sa.Date(), nullable=False))
    op.create_unique_constraint(
        "uq_bids_property_agent_date",
        "bids",
        ["property_id", "agent_id", "bid_date"],
    )

    op.drop_index("ix_lpm_property_id", table_name="lead_property_matches")
    op.drop_index("ix_lpm_lead_id", table_name="lead_property_matches")
    op.drop_table("lead_property_matches")

    op.drop_index("ix_leads_agent_id", table_name="leads")
    op.drop_table("leads")

    sa.Enum(name="lead_status").drop(op.get_bind(), checkfirst=True)
