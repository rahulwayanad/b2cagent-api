"""Match active properties to a lead and persist into lead_property_matches.

Scoring (max 100, min for inclusion 20):
  +30  b2c_rate <= budget_max (or budget_max is null)
  +20  total room capacity >= adults + children
  +20  property has photos
  +15  amenities count >= 3
  +15  b2c_rate >= budget_min (or budget_min is null)
   -10 if no single room sleeps the guest count
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Bid,
    BidStatus,
    Booking,
    BookingStatus,
    Lead,
    LeadPropertyMatch,
    LeadStatus,
    Property,
    PropertyAvailabilityBlock,
    PropertyStatus,
)


MIN_MATCH_SCORE = 20


def fits_guests(prop: Property, lead: Lead) -> bool:
    guests = lead.adults + (lead.children or 0)
    total_capacity = sum((r.capacity * r.count) for r in prop.rooms)
    return total_capacity >= guests


def _score(prop: Property, lead: Lead) -> int:
    score = 0
    guests = lead.adults + (lead.children or 0)
    max_room_capacity = max((r.capacity for r in prop.rooms), default=0)

    if lead.budget_max is None or prop.b2c_rate <= lead.budget_max:
        score += 30
    score += 20  # capacity check is enforced as hard filter upstream
    if len(prop.photos) > 0:
        score += 20
    if len(prop.amenities) >= 3:
        score += 15
    if lead.budget_min is None or prop.b2c_rate >= lead.budget_min:
        score += 15
    if max_room_capacity < guests:
        score -= 10
    return score


async def _candidate_properties(db: AsyncSession, lead: Lead) -> list[Property]:
    # Properties unavailable for the lead's dates: accepted bids, active
    # bookings, or manager-set availability blocks that overlap.
    bid_rows = await db.execute(
        select(Bid.property_id).where(
            Bid.status == BidStatus.accepted,
            Bid.check_in <= lead.check_out,
            Bid.check_out >= lead.check_in,
        )
    )
    booking_rows = await db.execute(
        select(Booking.property_id).where(
            Booking.status == BookingStatus.active,
            Booking.check_in <= lead.check_out,
            Booking.check_out >= lead.check_in,
        )
    )
    block_rows = await db.execute(
        select(PropertyAvailabilityBlock.property_id).where(
            PropertyAvailabilityBlock.start_date <= lead.check_out,
            PropertyAvailabilityBlock.end_date >= lead.check_in,
        )
    )
    busy_ids = (
        {row[0] for row in bid_rows.all()}
        | {row[0] for row in booking_rows.all()}
        | {row[0] for row in block_rows.all()}
    )

    result = await db.execute(
        select(Property)
        .where(Property.status == PropertyStatus.active)
        .options(
            selectinload(Property.rooms),
            selectinload(Property.amenities),
            selectinload(Property.photos),
        )
    )
    return [p for p in result.scalars().all() if p.id not in busy_ids]


async def match_properties_for_lead(
    lead: Lead, db: AsyncSession, *, replace_existing: bool = True
) -> int:
    """Compute matches for a lead and insert into lead_property_matches.

    Returns number of NEW matches added (existing matches are preserved when
    replace_existing=False, used for rematch).
    """
    candidates = await _candidate_properties(db, lead)

    if replace_existing:
        existing_property_ids: set = set()
        await db.execute(
            LeadPropertyMatch.__table__.delete().where(
                LeadPropertyMatch.lead_id == lead.id
            )
        )
    else:
        existing = await db.execute(
            select(LeadPropertyMatch.property_id).where(
                LeadPropertyMatch.lead_id == lead.id
            )
        )
        existing_property_ids = {pid for (pid,) in existing.all()}

    added = 0
    for prop in candidates:
        if prop.id in existing_property_ids:
            continue
        if not fits_guests(prop, lead):
            continue
        score = _score(prop, lead)
        if score < MIN_MATCH_SCORE:
            continue
        db.add(
            LeadPropertyMatch(
                lead_id=lead.id,
                property_id=prop.id,
                match_score=score,
            )
        )
        added += 1

    await db.commit()
    return added


async def expire_overdue_leads(db: AsyncSession, today: date | None = None) -> int:
    """Flip stale active leads to expired (cheap inline call from list/detail)."""
    today = today or date.today()
    result = await db.execute(
        select(Lead).where(
            Lead.status == LeadStatus.active,
            Lead.check_out < today,
        )
    )
    leads = list(result.scalars().all())
    for lead in leads:
        lead.status = LeadStatus.expired
    if leads:
        await db.commit()
    return len(leads)
