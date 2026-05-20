"""Bid payment flow.

Booking creation no longer happens at bid-accept time. Instead:
  1. Manager accepts bid → bid.status = accepted (no booking yet).
  2. Agent collects cash from the customer and POSTs to /bids/{id}/payment
     to record a payment in status=initiated.
  3. Manager confirms receipt via PATCH /bid-payments/{id}/confirm →
     payment.status=confirmed AND the Booking row is created here.

Online payments (future): a gateway webhook will create the payment record
directly in status=confirmed and trigger the same booking-creation path.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import require_active_role
from app.models import (
    Bid,
    BidPayment,
    BidStatus,
    Booking,
    BookingStatus,
    Lead,
    PaymentMethod,
    PaymentStatus,
    User,
    UserRole,
)
from app.schemas.bid_payment import BidPaymentCreateIn, BidPaymentOut

router = APIRouter(tags=["bid-payments"])

agent_dep = require_active_role(UserRole.agent)
manager_dep = require_active_role(UserRole.manager)


@router.post(
    "/bids/{bid_id}/payment",
    status_code=status.HTTP_201_CREATED,
    response_model=BidPaymentOut,
)
async def create_bid_payment(
    bid_id: uuid.UUID,
    payload: BidPaymentCreateIn,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> BidPaymentOut:
    bid = await db.scalar(
        select(Bid)
        .options(selectinload(Bid.payment))
        .where(Bid.id == bid_id)
    )
    if bid is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="bid not found"
        )
    if bid.agent_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not own this bid",
        )
    if bid.status != BidStatus.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payment can only be recorded on accepted bids",
        )
    if bid.payment is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="payment already recorded for this bid",
        )
    if payload.method == "online":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="online payment is not enabled yet",
        )

    payment = BidPayment(
        bid_id=bid.id,
        method=PaymentMethod.cash,
        status=PaymentStatus.initiated,
        amount=bid.amount,
        notes=payload.notes,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return BidPaymentOut.model_validate(payment)


@router.patch(
    "/bid-payments/{payment_id}/confirm", response_model=BidPaymentOut
)
async def confirm_bid_payment(
    payment_id: uuid.UUID,
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
) -> BidPaymentOut:
    payment = await db.scalar(
        select(BidPayment)
        .options(
            selectinload(BidPayment.bid).selectinload(Bid.property),
            selectinload(BidPayment.bid).selectinload(Bid.agent),
            selectinload(BidPayment.bid).selectinload(Bid.lead),
        )
        .where(BidPayment.id == payment_id)
    )
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="payment not found"
        )
    bid = payment.bid
    if bid.property.manager_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not own the property for this payment",
        )
    if payment.status == PaymentStatus.confirmed:
        # Idempotent — confirming twice should not double-book.
        return BidPaymentOut.model_validate(payment)

    payment.status = PaymentStatus.confirmed
    payment.confirmed_at = datetime.now(timezone.utc)

    # Booking is created on payment confirmation. No-op if one somehow exists
    # already (shouldn't, but guards against duplicates if the flow is rerun).
    existing_booking = await db.scalar(
        select(Booking).where(Booking.bid_id == bid.id)
    )
    if existing_booking is None:
        lead: Lead | None = bid.lead
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

    # Once the booking lands, every other live bid on this lead — same
    # property or different — loses. The customer is now booked; no other
    # manager should be able to accept a stale bid for them.
    others = (
        await db.scalars(
            select(Bid).where(
                Bid.lead_id == bid.lead_id,
                Bid.id != bid.id,
                Bid.status.in_(
                    [
                        BidStatus.pending,
                        BidStatus.on_hold,
                        BidStatus.accepted,
                    ]
                ),
            )
        )
    ).all()
    for o in others:
        o.status = BidStatus.rejected

    await db.commit()
    await db.refresh(payment)
    return BidPaymentOut.model_validate(payment)


# Light-weight introspection so the agent UI can poll for status if needed.
@router.get("/bids/{bid_id}/payment", response_model=BidPaymentOut | None)
async def get_bid_payment(
    bid_id: uuid.UUID,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> BidPaymentOut | None:
    bid = await db.scalar(
        select(Bid).options(selectinload(Bid.payment)).where(Bid.id == bid_id)
    )
    if bid is None or bid.agent_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="bid not found"
        )
    if bid.payment is None:
        return None
    return BidPaymentOut.model_validate(bid.payment)


