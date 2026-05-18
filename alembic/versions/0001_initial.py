"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


user_role_enum = sa.Enum("agent", "manager", name="user_role")
property_status_enum = sa.Enum("active", "booked", "closed", name="property_status")
bid_status_enum = sa.Enum(
    "pending", "accepted", "rejected", "withdrawn", name="bid_status"
)


def upgrade() -> None:
    user_role_enum.create(op.get_bind(), checkfirst=True)
    property_status_enum.create(op.get_bind(), checkfirst=True)
    bid_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("agent", "manager", name="user_role", create_type=False),
            nullable=False,
        ),
        sa.Column("google_sub", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("phone_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("google_sub", name="uq_users_google_sub"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=False)

    op.create_table(
        "properties",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "manager_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location_text", sa.String(512), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "booked", "closed", name="property_status", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column("b2b_rate", sa.Numeric(10, 2), nullable=False),
        sa.Column("b2c_rate", sa.Numeric(10, 2), nullable=False),
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
    op.create_index("ix_properties_manager_id", "properties", ["manager_id"])

    op.create_table(
        "property_rooms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("room_type", sa.String(128), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index("ix_property_rooms_property_id", "property_rooms", ["property_id"])

    op.create_table(
        "property_amenities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("icon_key", sa.String(64), nullable=True),
    )
    op.create_index("ix_property_amenities_property_id", "property_amenities", ["property_id"])

    op.create_table(
        "property_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_property_photos_property_id", "property_photos", ["property_id"])

    op.create_table(
        "bids",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("bid_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "accepted",
                "rejected",
                "withdrawn",
                name="bid_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
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
            "property_id",
            "agent_id",
            "bid_date",
            name="uq_bids_property_agent_date",
        ),
    )
    op.create_index("ix_bids_property_id", "bids", ["property_id"])
    op.create_index("ix_bids_agent_id", "bids", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_bids_agent_id", table_name="bids")
    op.drop_index("ix_bids_property_id", table_name="bids")
    op.drop_table("bids")

    op.drop_index("ix_property_photos_property_id", table_name="property_photos")
    op.drop_table("property_photos")

    op.drop_index("ix_property_amenities_property_id", table_name="property_amenities")
    op.drop_table("property_amenities")

    op.drop_index("ix_property_rooms_property_id", table_name="property_rooms")
    op.drop_table("property_rooms")

    op.drop_index("ix_properties_manager_id", table_name="properties")
    op.drop_table("properties")

    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    bid_status_enum.drop(op.get_bind(), checkfirst=True)
    property_status_enum.drop(op.get_bind(), checkfirst=True)
    user_role_enum.drop(op.get_bind(), checkfirst=True)
