"""Agent-facing booking endpoints.

A Booking row only exists after a bid is accepted *and* its payment is
confirmed (see bid_payments.py). These endpoints let an agent see their own
booked stays as a flat list, and look one up by lead so the lead detail page
can render its "Booking confirmed" card.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import require_active_role
from app.models import Booking, BookingStatus, User, UserRole
from app.schemas.booking import AgentBookingOut

router = APIRouter(tags=["bookings"])

agent_dep = require_active_role(UserRole.agent)


def _to_agent_booking(b: Booking) -> AgentBookingOut:
    return AgentBookingOut(
        id=b.id,
        property_id=b.property_id,
        property_name=b.property.name if b.property else "",
        property_location=b.property.location_text if b.property else None,
        lead_id=b.lead_id,
        bid_id=b.bid_id,
        customer_name=b.customer_name,
        customer_email=b.customer_email,
        customer_phone=b.customer_phone,
        check_in=b.check_in,
        check_out=b.check_out,
        guests=b.guests,
        amount=b.amount,
        status=b.status,
        created_at=b.created_at,
    )


@router.get("/bookings", response_model=list[AgentBookingOut])
async def list_agent_bookings(
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> list[AgentBookingOut]:
    rows = (
        await db.scalars(
            select(Booking)
            .options(selectinload(Booking.property))
            .where(
                Booking.agent_id == user.id,
                Booking.status == BookingStatus.active,
            )
            .order_by(Booking.check_in.desc())
        )
    ).all()
    return [_to_agent_booking(b) for b in rows]


@router.get(
    "/bookings/by-lead/{lead_id}", response_model=AgentBookingOut | None
)
async def get_agent_booking_by_lead(
    lead_id: uuid.UUID,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> AgentBookingOut | None:
    booking = await db.scalar(
        select(Booking)
        .options(selectinload(Booking.property))
        .where(
            Booking.lead_id == lead_id,
            Booking.agent_id == user.id,
            Booking.status == BookingStatus.active,
        )
    )
    if booking is None:
        return None
    return _to_agent_booking(booking)


@router.get(
    "/bookings/{booking_id}", response_model=AgentBookingOut
)
async def get_agent_booking(
    booking_id: uuid.UUID,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> AgentBookingOut:
    booking = await db.scalar(
        select(Booking)
        .options(selectinload(Booking.property))
        .where(Booking.id == booking_id, Booking.agent_id == user.id)
    )
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="booking not found"
        )
    return _to_agent_booking(booking)
