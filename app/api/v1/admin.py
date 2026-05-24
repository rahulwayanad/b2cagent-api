import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import (
    EmailTemplate,
    FieldConfig,
    SubscriptionPlan,
    User,
    UserRole,
    UserSubscription,
)
from app.schemas.catalog import FieldConfigOut, FieldConfigUpdate
from app.schemas.email_template import (
    EmailTemplateOut,
    EmailTemplateUpdateIn,
)
from app.services.lead_expiry_service import expire_overdue_leads
from app.schemas.subscription import (
    AssignPlanIn,
    PlanUpdateIn,
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


@router.patch(
    "/subscription-plans/{plan_id}", response_model=SubscriptionPlanOut
)
async def update_subscription_plan(
    plan_id: uuid.UUID,
    payload: PlanUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> SubscriptionPlan:
    plan = await db.get(SubscriptionPlan, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="subscription plan not found",
        )
    # exclude_unset so admins can clear a limit by sending null explicitly,
    # without forcing them to send every field on a partial edit.
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(plan, field, value)
    await db.commit()
    await db.refresh(plan)
    return plan


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
    try:
        from app.services.email_template_service import send_templated_email
        from app.services.notifications import get_email_sender

        await send_templated_email(
            db,
            get_email_sender(),
            code="subscription_upgraded",
            to=target.email,
            context={
                "name": target.full_name,
                "plan_name": plan.name,
                "bid_limit": plan.monthly_bid_limit
                if plan.monthly_bid_limit is not None
                else "unlimited",
                "property_limit": plan.monthly_property_limit
                if plan.monthly_property_limit is not None
                else "unlimited",
                "link_url": (
                    f"{settings.FRONTEND_BASE_URL.rstrip('/')}/manager/profile"
                ),
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return out  # type: ignore[return-value]


# ---- Email templates ------------------------------------------------------


@router.get("/email-templates", response_model=list[EmailTemplateOut])
async def list_email_templates(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> list[EmailTemplate]:
    rows = (
        await db.scalars(
            select(EmailTemplate).order_by(EmailTemplate.code.asc())
        )
    ).all()
    return list(rows)


@router.patch(
    "/email-templates/{template_id}", response_model=EmailTemplateOut
)
async def update_email_template(
    template_id: uuid.UUID,
    payload: EmailTemplateUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> EmailTemplate:
    tmpl = await db.get(EmailTemplate, template_id)
    if tmpl is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        )
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(tmpl, field, value)
    await db.commit()
    await db.refresh(tmpl)
    return tmpl


# ---- Maintenance jobs -----------------------------------------------------


@router.post("/jobs/expire-leads")
async def run_expire_leads_job(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(super_admin_dep),
) -> dict[str, int]:
    """Manual trigger for the lead-expiry sweep. The same sweep also runs
    hourly via the in-process scheduler."""
    return await expire_overdue_leads(db)
