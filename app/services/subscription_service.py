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
