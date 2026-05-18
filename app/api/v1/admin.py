from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import FieldConfig, User, UserRole
from app.schemas.catalog import FieldConfigOut, FieldConfigUpdate
from app.services.catalog import FIELD_CONFIG_ENTITIES
from app.services.field_config_service import ensure_defaults

router = APIRouter(prefix="/admin", tags=["admin"])

super_admin_dep = require_role(UserRole.super_admin)


@router.get(
    "/field-configs/{entity}", response_model=list[FieldConfigOut]
)
async def list_field_configs(
    entity: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[FieldConfig]:
    if entity not in FIELD_CONFIG_ENTITIES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown entity {entity!r}",
        )
    await ensure_defaults(db, entity)
    rows = (
        await db.scalars(
            select(FieldConfig)
            .where(FieldConfig.entity == entity)
            .order_by(FieldConfig.field_name.asc())
        )
    ).all()
    return list(rows)


@router.patch(
    "/field-configs/{entity}/{field_name}", response_model=FieldConfigOut
)
async def update_field_config(
    entity: str,
    field_name: str,
    payload: FieldConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> FieldConfig:
    if entity not in FIELD_CONFIG_ENTITIES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown entity {entity!r}",
        )
    if field_name not in FIELD_CONFIG_ENTITIES[entity]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown field {field_name!r} for entity {entity!r}",
        )
    await ensure_defaults(db, entity)
    config = await db.scalar(
        select(FieldConfig).where(
            FieldConfig.entity == entity,
            FieldConfig.field_name == field_name,
        )
    )
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="field config not found"
        )
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no fields supplied",
        )
    for key, value in updates.items():
        setattr(config, key, value)
    await db.commit()
    await db.refresh(config)
    return config
