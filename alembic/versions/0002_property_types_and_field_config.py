"""property types, basics, super_admin, and field_configs

Revision ID: 0002_property_types
Revises: 0001_initial
Create Date: 2026-05-15 00:00:00.000000

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_property_types"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROPERTY_TYPE_VALUES = [
    "house", "flat_apartment", "barn", "bed_breakfast", "boat", "cabin",
    "campervan", "casa_particular", "castle", "cave", "container",
    "cycladic_home", "dammuso", "dome", "earth_home", "farm", "guest_house",
    "hotel", "houseboat", "minsu", "riad", "ryokan", "shepherds_hut",
    "tent", "tiny_home", "tower", "tree_house", "trullo", "windmill", "yurt",
]
PRIVACY_TYPE_VALUES = ["entire_place", "a_room", "shared_room_hostel"]
PROPERTY_FIELDS = [
    "name", "description", "location_text", "lat", "lng",
    "b2b_rate", "b2c_rate", "property_type", "privacy_type",
    "guests", "bedrooms", "beds", "bathrooms", "min_guests", "max_guests",
]

property_type_enum = sa.Enum(*PROPERTY_TYPE_VALUES, name="property_type")
privacy_type_enum = sa.Enum(*PRIVACY_TYPE_VALUES, name="privacy_type")


def upgrade() -> None:
    bind = op.get_bind()

    # ALTER TYPE … ADD VALUE has to run outside a transaction in older PG;
    # 16+ tolerates it inside DDL transactions. Use IF NOT EXISTS for idempotency.
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'super_admin'")

    property_type_enum.create(bind, checkfirst=True)
    privacy_type_enum.create(bind, checkfirst=True)

    op.add_column(
        "properties",
        sa.Column(
            "property_type",
            sa.Enum(*PROPERTY_TYPE_VALUES, name="property_type", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "privacy_type",
            sa.Enum(*PRIVACY_TYPE_VALUES, name="privacy_type", create_type=False),
            nullable=True,
        ),
    )
    for col in ("guests", "bedrooms", "beds", "bathrooms", "min_guests", "max_guests"):
        op.add_column("properties", sa.Column(col, sa.Integer(), nullable=True))

    op.create_table(
        "field_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity", sa.String(64), nullable=False),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            "entity", "field_name", name="uq_field_configs_entity_field"
        ),
    )
    op.create_index("ix_field_configs_entity", "field_configs", ["entity"])

    field_configs = sa.table(
        "field_configs",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("entity", sa.String),
        sa.column("field_name", sa.String),
        sa.column("visible", sa.Boolean),
        sa.column("required", sa.Boolean),
    )
    op.bulk_insert(
        field_configs,
        [
            {
                "id": uuid.uuid4(),
                "entity": "property",
                "field_name": field,
                "visible": True,
                "required": False,
            }
            for field in PROPERTY_FIELDS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_field_configs_entity", table_name="field_configs")
    op.drop_table("field_configs")

    for col in ("max_guests", "min_guests", "bathrooms", "beds", "bedrooms", "guests"):
        op.drop_column("properties", col)
    op.drop_column("properties", "privacy_type")
    op.drop_column("properties", "property_type")

    bind = op.get_bind()
    privacy_type_enum.drop(bind, checkfirst=True)
    property_type_enum.drop(bind, checkfirst=True)
    # Note: PostgreSQL has no DROP VALUE for enums. The 'super_admin' value
    # added by upgrade() stays in user_role even after downgrade.
