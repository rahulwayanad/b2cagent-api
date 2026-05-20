import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import (
    FieldConfig,
    SubscriptionPlan,
    User,
    UserRole,
    UserSubscription,
)
from app.schemas.catalog import FieldConfigOut, FieldConfigUpdate
from app.schemas.subscription import (
    AssignPlanIn,
    SubscriptionPlanOut,
    UserSubscriptionOut,
)
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


# ---- Subscription plan catalog --------------------------------------------


@router.get("/subscription-plans", response_model=list[SubscriptionPlanOut])
async def list_subscription_plans(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> list[SubscriptionPlan]:
    rows = (
        await db.scalars(
            select(SubscriptionPlan).order_by(SubscriptionPlan.price.asc())
        )
    ).all()
    return list(rows)


# ---- User administration --------------------------------------------------


class UserAdminOut(BaseModel):
    """Admin-facing user row with the attached plan, if any."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    phone: str | None
    is_active: bool
    plan_code: str | None
    monthly_bid_limit: int | None
    created_at: datetime


async def _to_admin_row(u: User, db: AsyncSession) -> UserAdminOut:
    sub = await db.scalar(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.user_id == u.id)
    )
    plan = sub.plan if sub else None
    return UserAdminOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        phone=u.phone,
        is_active=u.is_active,
        plan_code=plan.code if plan else None,
        monthly_bid_limit=plan.monthly_bid_limit if plan else None,
        created_at=u.created_at,
    )


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> list[UserAdminOut]:
    users = (
        await db.scalars(select(User).order_by(User.created_at.desc()))
    ).all()
    return [await _to_admin_row(u, db) for u in users]


async def _load_target_user(
    user_id: uuid.UUID, admin: User, db: AsyncSession
) -> User:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )
    if target.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you cannot modify your own account here",
        )
    return target


@router.patch("/users/{user_id}/disable", response_model=UserAdminOut)
async def disable_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(super_admin_dep),
) -> UserAdminOut:
    target = await _load_target_user(user_id, admin, db)
    target.is_active = False
    await db.commit()
    return await _to_admin_row(target, db)


@router.patch("/users/{user_id}/enable", response_model=UserAdminOut)
async def enable_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(super_admin_dep),
) -> UserAdminOut:
    target = await _load_target_user(user_id, admin, db)
    target.is_active = True
    await db.commit()
    return await _to_admin_row(target, db)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(super_admin_dep),
) -> None:
    target = await _load_target_user(user_id, admin, db)
    await db.delete(target)
    await db.commit()


@router.post(
    "/users/{user_id}/subscription", response_model=UserSubscriptionOut
)
async def assign_user_plan(
    user_id: uuid.UUID,
    payload: AssignPlanIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(super_admin_dep),
) -> UserSubscription:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )
    plan = await db.scalar(
        select(SubscriptionPlan).where(
            SubscriptionPlan.code == payload.plan_code
        )
    )
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"plan {payload.plan_code!r} not found",
        )

    existing = await db.scalar(
        select(UserSubscription).where(UserSubscription.user_id == target.id)
    )
    now = datetime.now(timezone.utc)
    if existing is None:
        sub = UserSubscription(
            user_id=target.id,
            plan_id=plan.id,
            starts_at=now,
        )
        db.add(sub)
    else:
        existing.plan_id = plan.id
        existing.starts_at = now
        existing.expires_at = None
        sub = existing
    await db.commit()
    # Re-load with the plan relationship populated for the response.
    out = await db.scalar(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.id == sub.id)
    )
    return out  # type: ignore[return-value]
