"""Helpers around the FieldConfig table.

`ensure_defaults` lazily seeds rows from the canonical FIELD_CONFIG_ENTITIES
map. Lets tests work without running the migration, and protects production
if a newly-added field hasn't been migrated yet.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FieldConfig
from app.services.catalog import FIELD_CONFIG_ENTITIES


async def ensure_defaults(db: AsyncSession, entity: str) -> None:
    fields = FIELD_CONFIG_ENTITIES.get(entity, [])
    if not fields:
        return
    existing = set(
        (
            await db.scalars(
                select(FieldConfig.field_name).where(FieldConfig.entity == entity)
            )
        ).all()
    )
    missing = [f for f in fields if f not in existing]
    for field in missing:
        db.add(FieldConfig(entity=entity, field_name=field, visible=True, required=False))
    if missing:
        await db.commit()


async def get_disabled_fields(db: AsyncSession, entity: str) -> set[str]:
    rows = (
        await db.scalars(
            select(FieldConfig).where(
                FieldConfig.entity == entity, FieldConfig.visible == False  # noqa: E712
            )
        )
    ).all()
    return {r.field_name for r in rows}
