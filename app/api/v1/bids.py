"""Manager-side bid review API.

Agents now bid through /leads/{lead_id}/properties/{property_id}/bid only.
This module keeps the manager-facing endpoints: list bids on a property,
accept (auto-rejecting same-date pending bids on the same property), and
reject. Accepting a bid also flips the parent lead to status=won.

Property browsing for agents (without b2b_rate) lives here as well.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import require_active_role
from app.models import (
    Bid,
    BidStatus,
    Booking,
    BookingStatus,
    Lead,
    LeadStatus,
    Property,
    PropertyAvailabilityBlock,
    PropertyStatus,
    User,
    UserRole,
)
from app.schemas.bid import (
    AgentBidOut,
    BidWithAgentOut,
    ManagerBidOut,
    OptimalBidsOut,
)
from app.schemas.bid_payment import BidPaymentSummary
from app.schemas.property import (
    PropertyAvailableDetailOut,
    PropertyAvailableListOut,
    PropertyAvailableOut,
)
from app.services.notifications import (
    EmailSender,
    SMSSender,
    get_email_sender,
    get_sms_sender,
    send_bid_notification,
)
from app.services.subscription_service import check_manager_can_accept

router = APIRouter(tags=["bids"])

agent_dep = require_active_role(UserRole.agent)
manager_dep = require_active_role(UserRole.manager)


# ---- helpers ---------------------------------------------------------------


async def _load_bid_for_manager(
    bid_id: uuid.UUID, user: User, db: AsyncSession
) -> Bid:
    result = await db.execute(
        select(Bid)
        .options(
            selectinload(Bid.agent),
            selectinload(Bid.property),
            selectinload(Bid.lead),
            selectinload(Bid.payment),
        )
        .where(Bid.id == bid_id)
    )
    bid = result.scalar_one_or_none()
    if bid is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="bid not found"
        )
    if bid.property.manager_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not own the property for this bid",
        )
    return bid


def _queue_notification(
    bg: BackgroundTasks,
    *,
    bid: Bid,
    property_name: str,
    agent: User,
    email_sender: EmailSender,
    sms_sender: SMSSender,
) -> None:
    bg.add_task(
        send_bid_notification,
        email_sender=email_sender,
        sms_sender=sms_sender,
        agent_email=agent.email,
        agent_phone=agent.phone if agent.phone_verified else None,
        agent_name=agent.full_name,
        property_name=property_name,
        bid_date=bid.check_in.isoformat(),
        amount=str(bid.amount),
        status=bid.status.value,
    )


def _to_bid_with_agent(bid: Bid) -> BidWithAgentOut:
    lead = bid.lead
    prop = bid.property
    return BidWithAgentOut(
        id=bid.id,
        lead_id=bid.lead_id,
        property_id=bid.property_id,
        property_name=prop.name if prop else "",
        property_location=prop.location_text if prop else None,
        check_in=bid.check_in,
        check_out=bid.check_out,
        amount=bid.amount,
        status=bid.status,
        agent_id=bid.agent.id,
        agent_name=bid.agent.full_name,
        agent_email=bid.agent.email,
        customer_name=lead.customer_name if lead else "",
        adults=lead.adults if lead else 0,
        children=lead.children if lead else 0,
        created_at=bid.created_at,
        payment=BidPaymentSummary.model_validate(bid.payment)
        if bid.payment
        else None,
    )


# ---- Agent: own bids -------------------------------------------------------


@router.get("/bids", response_model=list[AgentBidOut])
async def list_my_bids(
    status_filter: BidStatus | None = Query(None, alias="status"),
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> list[AgentBidOut]:
    stmt = (
        select(Bid)
        .options(
            selectinload(Bid.property),
            selectinload(Bid.lead),
            selectinload(Bid.payment),
        )
        .where(Bid.agent_id == user.id)
        .order_by(Bid.created_at.desc())
    )
    if status_filter is not None:
        stmt = stmt.where(Bid.status == status_filter)
    rows = (await db.scalars(stmt)).all()
    return [
        AgentBidOut(
            id=b.id,
            lead_id=b.lead_id,
            property_id=b.property_id,
            property_name=b.property.name,
            property_location=b.property.location_text,
            customer_name=b.lead.customer_name,
            customer_phone=b.lead.customer_phone,
            check_in=b.check_in,
            check_out=b.check_out,
            adults=b.lead.adults,
            children=b.lead.children,
            amount=b.amount,
            status=b.status,
            created_at=b.created_at,
            payment=BidPaymentSummary.model_validate(b.payment)
            if b.payment
            else None,
        )
        for b in rows
    ]


# ---- Agent: property browsing (no b2b_rate) -------------------------------


@router.get("/properties/available", response_model=PropertyAvailableListOut)
async def list_available_properties(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> PropertyAvailableListOut:
    base = select(Property).where(Property.status == PropertyStatus.active)
    total = await db.scalar(
        select(func.count()).select_from(base.subquery())
    )
    items = (
        await db.scalars(
            base.options(selectinload(Property.rooms))
            .order_by(Property.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    def _to_out(p: Property) -> PropertyAvailableOut:
        room_count = sum(r.count or 0 for r in p.rooms)
        sleeps_count = sum(
            (r.capacity or 0) * (r.count or 0) for r in p.rooms
        )
        return PropertyAvailableOut.model_validate(p).model_copy(
            update={"room_count": room_count, "sleeps_count": sleeps_count}
        )

    return PropertyAvailableListOut(
        items=[_to_out(p) for p in items],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/properties/available/{property_id}",
    response_model=PropertyAvailableDetailOut,
)
async def get_available_property(
    property_id: uuid.UUID,
    _: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> PropertyAvailableDetailOut:
    result = await db.execute(
        select(Property)
        .where(
            Property.id == property_id,
            Property.status == PropertyStatus.active,
        )
        .options(
            selectinload(Property.rooms),
            selectinload(Property.amenities),
            selectinload(Property.photos),
        )
    )
    prop = result.scalar_one_or_none()
    if prop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="property not available"
        )
    room_count = sum(r.count or 0 for r in prop.rooms)
    sleeps_count = sum((r.capacity or 0) * (r.count or 0) for r in prop.rooms)
    return PropertyAvailableDetailOut.model_validate(prop).model_copy(
        update={"room_count": room_count, "sleeps_count": sleeps_count}
    )


# ---- Agent: check property availability for a date range -----------------


async def _availability_conflict(
    property_id: uuid.UUID,
    check_in: date,
    check_out: date,
    db: AsyncSession,
) -> tuple[str | None, str | None]:
    """Returns (conflict_type, reason) or (None, None) if free.

    Bookings: any active booking with overlapping date range.
    Blocks:   any manager-imposed availability block in the range.
    Overlap rule: existing.check_in <= request.check_out
                  AND existing.check_out >= request.check_in
    """
    overlapping_booking = await db.scalar(
        select(Booking).where(
            Booking.property_id == property_id,
            Booking.status == BookingStatus.active,
            Booking.check_in <= check_out,
            Booking.check_out >= check_in,
        )
    )
    if overlapping_booking is not None:
        return (
            "booking",
            f"Booked {overlapping_booking.check_in.isoformat()} → "
            f"{overlapping_booking.check_out.isoformat()}",
        )
    overlapping_block = await db.scalar(
        select(PropertyAvailabilityBlock).where(
            PropertyAvailabilityBlock.property_id == property_id,
            PropertyAvailabilityBlock.start_date <= check_out,
            PropertyAvailabilityBlock.end_date >= check_in,
        )
    )
    if overlapping_block is not None:
        return (
            "block",
            f"Closed by manager {overlapping_block.start_date.isoformat()} → "
            f"{overlapping_block.end_date.isoformat()}",
        )
    return (None, None)


@router.get("/properties/available/{property_id}/availability")
async def check_availability(
    property_id: uuid.UUID,
    check_in: str = Query(..., description="YYYY-MM-DD"),
    check_out: str = Query(..., description="YYYY-MM-DD"),
    _: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from datetime import date as _date

    try:
        ci = _date.fromisoformat(check_in)
        co = _date.fromisoformat(check_out)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid date: {e}",
        ) from e
    if co < ci:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="check_out must be on or after check_in",
        )
    prop = await db.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.status == PropertyStatus.active,
        )
    )
    if prop is None:
        return {
            "available": False,
            "conflict_type": "inactive",
            "reason": "Property not available for bidding",
        }
    conflict_type, reason = await _availability_conflict(property_id, ci, co, db)
    return {
        "available": conflict_type is None,
        "conflict_type": conflict_type,
        "reason": reason,
    }


# ---- Manager: aggregate bid feed ------------------------------------------


@router.get("/manager/bids", response_model=list[ManagerBidOut])
async def list_manager_bids(
    status_filter: BidStatus | None = Query(None, alias="status"),
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
) -> list[ManagerBidOut]:
    stmt = (
        select(Bid)
        .join(Bid.property)
        .options(
            selectinload(Bid.property),
            selectinload(Bid.agent),
            selectinload(Bid.lead),
            selectinload(Bid.payment),
        )
        .where(Property.manager_id == user.id)
        .order_by(Bid.created_at.desc())
    )
    if status_filter is not None:
        stmt = stmt.where(Bid.status == status_filter)
    rows = (await db.scalars(stmt)).all()
    return [
        ManagerBidOut(
            id=b.id,
            lead_id=b.lead_id,
            property_id=b.property_id,
            property_name=b.property.name,
            property_location=b.property.location_text,
            agent_id=b.agent.id,
            agent_name=b.agent.full_name,
            agent_email=b.agent.email,
            customer_name=b.lead.customer_name,
            check_in=b.check_in,
            check_out=b.check_out,
            adults=b.lead.adults,
            children=b.lead.children,
            amount=b.amount,
            status=b.status,
            created_at=b.created_at,
            payment=BidPaymentSummary.model_validate(b.payment)
            if b.payment
            else None,
        )
        for b in rows
    ]


# ---- Manager: view + decide -----------------------------------------------


@router.get(
    "/properties/{property_id}/bids", response_model=list[BidWithAgentOut]
)
async def list_property_bids(
    property_id: uuid.UUID,
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
) -> list[BidWithAgentOut]:
    prop = await db.get(Property, property_id)
    if prop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="property not found"
        )
    if prop.manager_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not own this property",
        )
    result = await db.execute(
        select(Bid)
        .options(
            selectinload(Bid.agent),
            selectinload(Bid.lead),
            selectinload(Bid.payment),
        )
        .where(Bid.property_id == property_id)
        .order_by(Bid.created_at.desc())
    )
    return [_to_bid_with_agent(b) for b in result.scalars().all()]


@router.get(
    "/properties/{property_id}/bids/optimal", response_model=OptimalBidsOut
)
async def optimal_property_bids(
    property_id: uuid.UUID,
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
) -> OptimalBidsOut:
    prop = await db.get(Property, property_id)
    if prop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="property not found"
        )
    if prop.manager_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not own this property",
        )

    pending = (
        await db.scalars(
            select(Bid)
            .where(
                Bid.property_id == property_id,
                Bid.status == BidStatus.pending,
            )
            .order_by(Bid.check_out.asc(), Bid.check_in.asc())
        )
    ).all()

    if not pending:
        return OptimalBidsOut(
            recommended_bid_ids=[],
            total_amount=Decimal("0"),
            top_single_bid_id=None,
            top_single_amount=Decimal("0"),
        )

    # Weighted interval scheduling. Intervals are inclusive on both ends
    # (matches the accept-time overlap rule: check_in <= other.check_out AND
    # check_out >= other.check_in). Two bids are non-overlapping iff one ends
    # strictly before the other starts.
    n = len(pending)
    prev = [-1] * n
    for i in range(n):
        for j in range(i - 1, -1, -1):
            if pending[j].check_out < pending[i].check_in:
                prev[i] = j
                break

    dp: list[Decimal] = [Decimal("0")] * n
    take = [False] * n
    for i in range(n):
        with_i = pending[i].amount + (
            dp[prev[i]] if prev[i] >= 0 else Decimal("0")
        )
        without_i = dp[i - 1] if i > 0 else Decimal("0")
        if with_i > without_i:
            dp[i] = with_i
            take[i] = True
        else:
            dp[i] = without_i

    chosen: list[uuid.UUID] = []
    i = n - 1
    while i >= 0:
        if take[i]:
            chosen.append(pending[i].id)
            i = prev[i]
        else:
            i -= 1
    chosen.reverse()

    top_single = max(pending, key=lambda b: b.amount)

    return OptimalBidsOut(
        recommended_bid_ids=chosen,
        total_amount=dp[-1],
        top_single_bid_id=top_single.id,
        top_single_amount=top_single.amount,
    )


@router.patch("/bids/{bid_id}/accept", response_model=BidWithAgentOut)
async def accept_bid(
    bid_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
    sms_sender: SMSSender = Depends(get_sms_sender),
) -> BidWithAgentOut:
    bid = await _load_bid_for_manager(bid_id, user, db)
    if bid.status != BidStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"cannot accept bid in status={bid.status.value}",
        )

    # Enforce monthly accept quota for the manager's plan.
    await check_manager_can_accept(user, db)

    # Put overlapping pending bids on hold (not reject) so they can be
    # revived if the accepted bid is withdrawn or declined before payment.
    others = (
        await db.scalars(
            select(Bid)
            .options(selectinload(Bid.agent))
            .where(
                Bid.property_id == bid.property_id,
                Bid.id != bid.id,
                Bid.status == BidStatus.pending,
                Bid.check_in <= bid.check_out,
                Bid.check_out >= bid.check_in,
            )
        )
    ).all()
    for other in others:
        other.status = BidStatus.on_hold

    bid.status = BidStatus.accepted
    # Stamp the accept moment so the manager's monthly quota counts this
    # action even if the bid is later withdrawn or rejected.
    from datetime import datetime, timezone
    bid.accepted_at = datetime.now(timezone.utc)

    # Flip the parent lead to won. The Booking row is NOT created here anymore
    # — it lands when the BidPayment is confirmed (cash) or captured (online).
    lead = await db.get(Lead, bid.lead_id)
    if lead is not None and lead.status == LeadStatus.active:
        lead.status = LeadStatus.won

    await db.commit()

    property_name = bid.property.name
    _queue_notification(
        background_tasks,
        bid=bid,
        property_name=property_name,
        agent=bid.agent,
        email_sender=email_sender,
        sms_sender=sms_sender,
    )
    for other in others:
        _queue_notification(
            background_tasks,
            bid=other,
            property_name=property_name,
            agent=other.agent,
            email_sender=email_sender,
            sms_sender=sms_sender,
        )
    return _to_bid_with_agent(bid)


async def _revive_held_bids(bid: Bid, db: AsyncSession) -> None:
    """When an accepted bid is removed before booking, restore any bids
    that were put on hold because they overlapped with it."""
    held = (
        await db.scalars(
            select(Bid).where(
                Bid.property_id == bid.property_id,
                Bid.id != bid.id,
                Bid.status == BidStatus.on_hold,
                Bid.check_in <= bid.check_out,
                Bid.check_out >= bid.check_in,
            )
        )
    ).all()
    for h in held:
        h.status = BidStatus.pending


async def _revert_lead_to_active(bid: Bid, db: AsyncSession) -> None:
    """The lead was flipped to `won` when this bid was accepted. If the
    bid is now rolled back before payment, the lead is up for grabs again."""
    lead = await db.get(Lead, bid.lead_id)
    if lead is not None and lead.status == LeadStatus.won:
        lead.status = LeadStatus.active


@router.patch("/bids/{bid_id}/reject", response_model=BidWithAgentOut)
async def reject_bid(
    bid_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
    sms_sender: SMSSender = Depends(get_sms_sender),
) -> BidWithAgentOut:
    bid = await _load_bid_for_manager(bid_id, user, db)
    if bid.status == BidStatus.pending:
        bid.status = BidStatus.rejected
    elif bid.status == BidStatus.accepted and bid.payment is None:
        # Manager changed their mind before the agent collected payment.
        # Roll back: revive the held bids and free the lead.
        bid.status = BidStatus.rejected
        await _revert_lead_to_active(bid, db)
        await _revive_held_bids(bid, db)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"cannot reject bid in status={bid.status.value}"
            + (" with a payment already recorded" if bid.payment else ""),
        )
    await db.commit()
    _queue_notification(
        background_tasks,
        bid=bid,
        property_name=bid.property.name,
        agent=bid.agent,
        email_sender=email_sender,
        sms_sender=sms_sender,
    )
    return _to_bid_with_agent(bid)
