"""Manager-side bid review API.

Agents now bid through /leads/{lead_id}/properties/{property_id}/bid only.
This module keeps the manager-facing endpoints: list bids on a property,
accept (auto-rejecting same-date pending bids on the same property), and
reject. Accepting a bid also flips the parent lead to status=won.

Property browsing for agents (without b2b_rate) lives here as well.
"""
from __future__ import annotations

import uuid

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
    PropertyStatus,
    User,
    UserRole,
)
from app.schemas.bid import BidWithAgentOut
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

router = APIRouter(tags=["bids"])

agent_dep = require_active_role(UserRole.agent)
manager_dep = require_active_role(UserRole.manager)


# ---- helpers ---------------------------------------------------------------


async def _load_bid_for_manager(
    bid_id: uuid.UUID, user: User, db: AsyncSession
) -> Bid:
    result = await db.execute(
        select(Bid)
        .options(selectinload(Bid.agent), selectinload(Bid.property))
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
    return BidWithAgentOut(
        id=bid.id,
        property_id=bid.property_id,
        check_in=bid.check_in,
        check_out=bid.check_out,
        amount=bid.amount,
        status=bid.status,
        agent_id=bid.agent.id,
        agent_name=bid.agent.full_name,
        agent_email=bid.agent.email,
        created_at=bid.created_at,
    )


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
            base.order_by(Property.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return PropertyAvailableListOut(
        items=[PropertyAvailableOut.model_validate(p) for p in items],
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
    return PropertyAvailableDetailOut.model_validate(prop)


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
        .options(selectinload(Bid.agent))
        .where(Bid.property_id == property_id)
        .order_by(Bid.amount.desc())
    )
    return [_to_bid_with_agent(b) for b in result.scalars().all()]


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

    # Auto-reject any other pending bids on the same property whose date range
    # overlaps with this one.
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
        other.status = BidStatus.rejected

    bid.status = BidStatus.accepted

    # Flip the parent lead to won + create a Booking from the lead's customer.
    lead = await db.get(Lead, bid.lead_id)
    if lead is not None and lead.status == LeadStatus.active:
        lead.status = LeadStatus.won

    booking = Booking(
        property_id=bid.property_id,
        lead_id=bid.lead_id,
        bid_id=bid.id,
        agent_id=bid.agent_id,
        customer_name=lead.customer_name if lead else bid.agent.full_name,
        customer_email=lead.customer_email if lead else bid.agent.email,
        customer_phone=lead.customer_phone if lead else bid.agent.phone,
        check_in=bid.check_in,
        check_out=bid.check_out,
        guests=(lead.adults + (lead.children or 0)) if lead else 1,
        amount=bid.amount,
        status=BookingStatus.active,
    )
    db.add(booking)

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
    if bid.status != BidStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"cannot reject bid in status={bid.status.value}",
        )
    bid.status = BidStatus.rejected
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
