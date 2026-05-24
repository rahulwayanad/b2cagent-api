"""Plan lookups + monthly bid-quota enforcement.

Free users have no UserSubscription row — they're implicitly on the seeded
'free' plan. The admin/super_admin role is exempt from quotas regardless of
plan, since they're operating the system rather than competing in it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Bid,
    Property,
    SubscriptionPlan,
    User,
    UserRole,
    UserSubscription,
)


_FREE_DEFAULT_LIMIT = 10


def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def get_user_plan(
    user: User, db: AsyncSession
) -> SubscriptionPlan | None:
    """Return the SubscriptionPlan attached to this user, or None if no row
    exists (in which case treat as the seeded 'free' plan or fall back to the
    default limit)."""
    sub = await db.scalar(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.user_id == user.id)
    )
    return sub.plan if sub is not None else None


async def _resolve_limit(user: User, db: AsyncSession) -> int | None:
    plan = await get_user_plan(user, db)
    if plan is None:
        # No row → free tier. Look up the seeded free plan for its limit;
        # falling back to a hardcoded default if even that's missing.
        free = await db.scalar(
            select(SubscriptionPlan).where(SubscriptionPlan.code == "free")
        )
        return free.monthly_bid_limit if free else _FREE_DEFAULT_LIMIT
    return plan.monthly_bid_limit


async def check_agent_can_bid(user: User, db: AsyncSession) -> None:
    """Raise 429 if this agent has hit their monthly bid quota."""
    if user.role == UserRole.super_admin:
        return
    limit = await _resolve_limit(user, db)
    if limit is None:
        return  # unlimited
    used = await db.scalar(
        select(func.count(Bid.id)).where(
            Bid.agent_id == user.id,
            Bid.created_at >= _month_start_utc(),
        )
    )
    if (used or 0) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Monthly bid limit reached ({limit} this month). "
                "Upgrade your plan to place more bids."
            ),
        )


async def check_manager_can_accept(
    user: User, db: AsyncSession
) -> None:
    """Raise 429 if this manager has hit their monthly accept quota."""
    if user.role == UserRole.super_admin:
        return
    limit = await _resolve_limit(user, db)
    if limit is None:
        return  # unlimited
    used = await db.scalar(
        select(func.count(Bid.id))
        .join(Property, Bid.property_id == Property.id)
        .where(
            Property.manager_id == user.id,
            Bid.accepted_at.is_not(None),
            Bid.accepted_at >= _month_start_utc(),
        )
    )
    if (used or 0) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Monthly accept limit reached ({limit} this month). "
                "Upgrade your plan to accept more bids."
            ),
        )


async def agent_quota_summary(
    user: User, db: AsyncSession
) -> tuple[str, int | None, int]:
    """Return (plan_code, limit, used) for the agent's bid placement quota."""
    plan = await get_user_plan(user, db)
    code = plan.code if plan else "free"
    limit = await _resolve_limit(user, db)
    used = await db.scalar(
        select(func.count(Bid.id)).where(
            Bid.agent_id == user.id,
            Bid.created_at >= _month_start_utc(),
        )
    )
    return code, limit, int(used or 0)


async def manager_quota_summary(
    user: User, db: AsyncSession
) -> tuple[str, int | None, int]:
    plan = await get_user_plan(user, db)
    code = plan.code if plan else "free"
    limit = await _resolve_limit(user, db)
    used = await db.scalar(
        select(func.count(Bid.id))
        .join(Property, Bid.property_id == Property.id)
        .where(
            Property.manager_id == user.id,
            Bid.accepted_at.is_not(None),
            Bid.accepted_at >= _month_start_utc(),
        )
    )
    return code, limit, int(used or 0)


async def _resolve_plan_for_display(
    user: User, db: AsyncSession
) -> SubscriptionPlan:
    """Like get_user_plan but always returns a plan object — falls back to the
    seeded 'free' row when the user has no subscription. Raises if the free
    plan is missing (shouldn't happen in a properly migrated DB)."""
    plan = await get_user_plan(user, db)
    if plan is not None:
        return plan
    free = await db.scalar(
        select(SubscriptionPlan).where(SubscriptionPlan.code == "free")
    )
    assert free is not None, "free plan must be seeded"
    return free


async def my_subscription_summary(
    user: User, db: AsyncSession
) -> dict:
    """Profile-page payload covering the active_role's bid quota and the
    user's property usage. Agents count bids they've placed this month;
    managers count bids they've accepted this month."""
    plan = await _resolve_plan_for_display(user, db)

    is_manager_view = (
        user.active_role == UserRole.manager or user.role == UserRole.manager
    )

    if is_manager_view:
        bids_used = await db.scalar(
            select(func.count(Bid.id))
            .join(Property, Bid.property_id == Property.id)
            .where(
                Property.manager_id == user.id,
                Bid.accepted_at.is_not(None),
                Bid.accepted_at >= _month_start_utc(),
            )
        ) or 0
        quota_basis = "bids_accepted"
    else:
        bids_used = await db.scalar(
            select(func.count(Bid.id)).where(
                Bid.agent_id == user.id,
                Bid.created_at >= _month_start_utc(),
            )
        ) or 0
        quota_basis = "bids_placed"

    properties_used = await db.scalar(
        select(func.count(Property.id)).where(Property.manager_id == user.id)
    ) or 0

    bids_remaining = (
        None
        if plan.monthly_bid_limit is None
        else max(0, plan.monthly_bid_limit - int(bids_used))
    )
    properties_remaining = (
        None
        if plan.monthly_property_limit is None
        else max(0, plan.monthly_property_limit - int(properties_used))
    )

    return {
        "plan_code": plan.code,
        "plan_name": plan.name,
        "price": plan.price,
        "monthly_bid_limit": plan.monthly_bid_limit,
        "monthly_property_limit": plan.monthly_property_limit,
        "broker_phone_visible": plan.broker_phone_visible,
        "bids_used_this_month": int(bids_used),
        "bids_remaining": bids_remaining,
        "properties_used": int(properties_used),
        "properties_remaining": properties_remaining,
        "quota_basis": quota_basis,
    }
