import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
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
    LeadPropertyMatch,
    LeadStatus,
    Property,
    PropertyAvailabilityBlock,
    PropertyStatus,
    User,
    UserRole,
)
from app.schemas.lead import (
    BidResponse,
    BidSummary,
    LeadCreate,
    LeadListResponse,
    LeadResponse,
    LeadStatusUpdate,
    LeadUpdate,
    MatchedPropertyListResponse,
    MatchedPropertyResponse,
    PlaceBidIn,
    RematchResponse,
)
from app.services.lead_matching_service import (
    expire_overdue_leads,
    match_properties_for_lead,
)

router = APIRouter(prefix="/leads", tags=["leads"])

agent_dep = require_active_role(UserRole.agent)


# ---- helpers --------------------------------------------------------------


async def _get_owned_lead(
    lead_id: uuid.UUID, user: User, db: AsyncSession
) -> Lead:
    lead = await db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found"
        )
    if lead.agent_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this lead",
        )
    return lead


# Must mirror frontend MAX_DISTANCE_KM in LeadDetailPage so the count shown
# in the leads list ("0/9") matches the matches the agent actually sees.
_MATCHED_RADIUS_KM = 100.0


def _haversine_km(
    a_lat: float, a_lng: float, b_lat: float, b_lng: float
) -> float:
    from math import asin, cos, radians, sin, sqrt

    R = 6371.0
    dlat = radians(b_lat - a_lat)
    dlng = radians(b_lng - a_lng)
    s = (
        sin(dlat / 2) ** 2
        + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlng / 2) ** 2
    )
    return 2 * R * asin(sqrt(s))


async def _counts_for_lead(lead_id: uuid.UUID, db: AsyncSession) -> tuple[int, int]:
    # Load matches + property fields so we can apply the same visibility rules
    # the frontend uses (must have coordinates, must be within radius of
    # customer's preferred location when set, property must be active).
    lead = await db.get(Lead, lead_id)
    rows = (
        await db.execute(
            select(LeadPropertyMatch, Property)
            .join(Property, LeadPropertyMatch.property_id == Property.id)
            .where(
                LeadPropertyMatch.lead_id == lead_id,
                LeadPropertyMatch.is_hidden.is_(False),
            )
        )
    ).all()

    has_origin = (
        lead is not None
        and lead.customer_lat is not None
        and lead.customer_lng is not None
    )

    match_count = 0
    for _match, prop in rows:
        if prop.status != PropertyStatus.active:
            continue
        if prop.lat is None or prop.lng is None:
            continue
        if has_origin:
            d = _haversine_km(
                lead.customer_lat, lead.customer_lng, prop.lat, prop.lng
            )
            if d > _MATCHED_RADIUS_KM:
                continue
        match_count += 1

    bid_count = await db.scalar(
        select(func.count(Bid.id)).where(
            Bid.lead_id == lead_id,
            Bid.status != BidStatus.withdrawn,
        )
    )
    return match_count, int(bid_count or 0)


def _lead_to_response(lead: Lead, matches: int, bids: int) -> LeadResponse:
    return LeadResponse(
        id=lead.id,
        customer_name=lead.customer_name,
        customer_email=lead.customer_email,
        customer_phone=lead.customer_phone,
        customer_location_text=lead.customer_location_text,
        customer_lat=lead.customer_lat,
        customer_lng=lead.customer_lng,
        check_in=lead.check_in,
        check_out=lead.check_out,
        is_single_day=lead.is_single_day,
        adults=lead.adults,
        children=lead.children,
        budget_min=lead.budget_min,
        budget_max=lead.budget_max,
        special_requirements=lead.special_requirements,
        notes=lead.notes,
        status=lead.status,
        matched_properties_count=matches,
        bids_count=bids,
        created_at=lead.created_at,
    )


# ---- endpoints ------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=LeadResponse)
async def create_lead(
    payload: LeadCreate,
    background: BackgroundTasks,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    lead = Lead(
        agent_id=user.id,
        customer_name=payload.customer_name,
        customer_email=payload.customer_email,
        customer_phone=payload.customer_phone,
        customer_location_text=payload.customer_location_text,
        customer_lat=payload.customer_lat,
        customer_lng=payload.customer_lng,
        check_in=payload.check_in,
        check_out=payload.check_out,
        is_single_day=payload.check_in == payload.check_out,
        adults=payload.adults,
        children=payload.children,
        budget_min=payload.budget_min,
        budget_max=payload.budget_max,
        special_requirements=payload.special_requirements,
        notes=payload.notes,
        status=LeadStatus.active,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)

    # Inline match — we need the count for the response. Background tasks would
    # delay this and the client would see 0 matches on the first render.
    await match_properties_for_lead(lead, db, replace_existing=True)
    matches, bids = await _counts_for_lead(lead.id, db)
    return _lead_to_response(lead, matches, bids)


@router.get("", response_model=LeadListResponse)
async def list_leads(
    status_filter: LeadStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> LeadListResponse:
    await expire_overdue_leads(db)

    base = select(Lead).where(Lead.agent_id == user.id)
    if status_filter is not None:
        base = base.where(Lead.status == status_filter)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    offset = (page - 1) * limit
    items = (
        await db.scalars(
            base.order_by(Lead.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()

    out: list[LeadResponse] = []
    for lead in items:
        matches, bids = await _counts_for_lead(lead.id, db)
        out.append(_lead_to_response(lead, matches, bids))
    return LeadListResponse(items=out, total=int(total or 0), page=page, limit=limit)


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: uuid.UUID,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    await expire_overdue_leads(db)
    lead = await _get_owned_lead(lead_id, user, db)
    matches, bids = await _counts_for_lead(lead.id, db)
    return _lead_to_response(lead, matches, bids)


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    lead = await _get_owned_lead(lead_id, user, db)
    if lead.status in (LeadStatus.won, LeadStatus.lost, LeadStatus.expired):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot update lead in status={lead.status.value}",
        )
    updates = payload.model_dump(exclude_unset=True)
    # Track which fields impact property matching — when they change we re-run
    # the matcher so the agent's matched-properties list stays in sync.
    rematch_fields = {"check_in", "check_out", "adults", "children"}
    needs_rematch = any(k in updates for k in rematch_fields)

    for k, v in updates.items():
        setattr(lead, k, v)
    # Keep is_single_day consistent with the stored date range.
    if "check_in" in updates or "check_out" in updates:
        lead.is_single_day = lead.check_in == lead.check_out
    # Cross-field guard in case only one date was sent and now they're inverted.
    if lead.check_out < lead.check_in:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="check_out must be on or after check_in",
        )

    await db.commit()
    await db.refresh(lead)

    if needs_rematch:
        await match_properties_for_lead(lead, db, replace_existing=True)

    matches, bids = await _counts_for_lead(lead.id, db)
    return _lead_to_response(lead, matches, bids)


@router.patch("/{lead_id}/status", response_model=LeadResponse)
async def update_lead_status(
    lead_id: uuid.UUID,
    payload: LeadStatusUpdate,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    lead = await _get_owned_lead(lead_id, user, db)
    if lead.status in (LeadStatus.won, LeadStatus.expired):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot change status of {lead.status.value} lead",
        )
    lead.status = LeadStatus.lost
    await db.commit()
    await db.refresh(lead)
    matches, bids = await _counts_for_lead(lead.id, db)
    return _lead_to_response(lead, matches, bids)


@router.get("/{lead_id}/properties", response_model=MatchedPropertyListResponse)
async def get_lead_properties(
    lead_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> MatchedPropertyListResponse:
    lead = await _get_owned_lead(lead_id, user, db)

    base = (
        select(LeadPropertyMatch)
        .where(LeadPropertyMatch.lead_id == lead.id)
        .options(
            selectinload(LeadPropertyMatch.property).selectinload(Property.rooms),
            selectinload(LeadPropertyMatch.property).selectinload(Property.amenities),
            selectinload(LeadPropertyMatch.property).selectinload(Property.photos),
        )
        .order_by(LeadPropertyMatch.match_score.desc())
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    offset = (page - 1) * limit
    matches = (await db.scalars(base.limit(limit).offset(offset))).all()

    # Existing bids for this lead, keyed by property_id (latest non-withdrawn wins).
    bids_result = await db.execute(
        select(Bid).where(
            Bid.lead_id == lead.id,
        )
    )
    bids_by_prop: dict[uuid.UUID, Bid] = {}
    for b in bids_result.scalars().all():
        existing = bids_by_prop.get(b.property_id)
        if existing is None or (
            existing.status == BidStatus.withdrawn and b.status != BidStatus.withdrawn
        ):
            bids_by_prop[b.property_id] = b

    items: list[MatchedPropertyResponse] = []
    for m in matches:
        # Return hidden matches too so the agent can reveal them via the
        # "Show hidden" toggle on the lead detail page.
        prop = m.property
        primary_photo = next(
            (p for p in prop.photos if p.is_primary), prop.photos[0] if prop.photos else None
        )
        photos_payload = []
        if primary_photo is not None:
            photos_payload.append(primary_photo)
        bid = bids_by_prop.get(prop.id)
        items.append(
            MatchedPropertyResponse(
                property_id=prop.id,
                name=prop.name,
                location_text=prop.location_text,
                street=prop.street,
                city=prop.city,
                state=prop.state,
                country=prop.country,
                lat=prop.lat,
                lng=prop.lng,
                property_type=prop.property_type.value if prop.property_type else None,
                b2c_rate=prop.b2c_rate,
                b2b_rate=prop.b2b_rate,
                photos=photos_payload,
                amenities=prop.amenities,
                room_summary=prop.rooms,
                match_score=m.match_score,
                is_hidden=m.is_hidden,
                existing_bid=BidSummary(id=bid.id, amount=bid.amount, status=bid.status)
                if bid is not None
                else None,
            )
        )

    return MatchedPropertyListResponse(
        items=items, total=int(total or 0), page=page, limit=limit
    )


async def _get_match(
    lead_id: uuid.UUID, property_id: uuid.UUID, db: AsyncSession
) -> LeadPropertyMatch:
    match = await db.scalar(
        select(LeadPropertyMatch).where(
            LeadPropertyMatch.lead_id == lead_id,
            LeadPropertyMatch.property_id == property_id,
        )
    )
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property is not matched to this lead",
        )
    return match


@router.post("/{lead_id}/properties/{property_id}/hide")
async def hide_property(
    lead_id: uuid.UUID,
    property_id: uuid.UUID,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_owned_lead(lead_id, user, db)
    match = await _get_match(lead_id, property_id, db)
    match.is_hidden = True
    await db.commit()
    return {"success": True}


@router.post("/{lead_id}/properties/{property_id}/unhide")
async def unhide_property(
    lead_id: uuid.UUID,
    property_id: uuid.UUID,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_owned_lead(lead_id, user, db)
    match = await _get_match(lead_id, property_id, db)
    match.is_hidden = False
    await db.commit()
    return {"success": True}


@router.post(
    "/{lead_id}/properties/{property_id}/bid",
    status_code=status.HTTP_201_CREATED,
    response_model=BidResponse,
)
async def place_bid(
    lead_id: uuid.UUID,
    property_id: uuid.UUID,
    payload: PlaceBidIn,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> BidResponse:
    lead = await _get_owned_lead(lead_id, user, db)
    if lead.status != LeadStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lead is not active (status={lead.status.value})",
        )
    await _get_match(lead.id, property_id, db)

    prop = await db.get(Property, property_id)
    if prop is None or prop.status != PropertyStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Property is not available",
        )

    if payload.amount < prop.b2b_rate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bid amount is below the accepted minimum",
        )

    # Availability gate — block bids if the requested dates clash with an
    # existing booking or a manager-imposed block.
    overlapping_booking = await db.scalar(
        select(Booking).where(
            Booking.property_id == property_id,
            Booking.status == BookingStatus.active,
            Booking.check_in <= lead.check_out,
            Booking.check_out >= lead.check_in,
        )
    )
    if overlapping_booking is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Property is already booked "
                f"{overlapping_booking.check_in.isoformat()} → "
                f"{overlapping_booking.check_out.isoformat()}"
            ),
        )
    overlapping_block = await db.scalar(
        select(PropertyAvailabilityBlock).where(
            PropertyAvailabilityBlock.property_id == property_id,
            PropertyAvailabilityBlock.start_date <= lead.check_out,
            PropertyAvailabilityBlock.end_date >= lead.check_in,
        )
    )
    if overlapping_block is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Property is closed by the manager "
                f"{overlapping_block.start_date.isoformat()} → "
                f"{overlapping_block.end_date.isoformat()}"
            ),
        )

    existing = await db.scalar(
        select(Bid).where(Bid.lead_id == lead.id, Bid.property_id == property_id)
    )
    if existing is not None and existing.status != BidStatus.withdrawn:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active bid already exists for this property on this lead",
        )
    if existing is not None and existing.status == BidStatus.withdrawn:
        # Re-bid on a previously-withdrawn slot: reuse the row.
        existing.amount = payload.amount
        existing.status = BidStatus.pending
        existing.check_in = lead.check_in
        existing.check_out = lead.check_out
        bid = existing
    else:
        bid = Bid(
            lead_id=lead.id,
            property_id=property_id,
            agent_id=user.id,
            check_in=lead.check_in,
            check_out=lead.check_out,
            amount=payload.amount,
            status=BidStatus.pending,
        )
        db.add(bid)

    await db.commit()
    await db.refresh(bid)
    return BidResponse.model_validate(bid)


@router.delete("/{lead_id}/properties/{property_id}/bid")
async def withdraw_bid(
    lead_id: uuid.UUID,
    property_id: uuid.UUID,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> dict:
    lead = await _get_owned_lead(lead_id, user, db)
    bid = await db.scalar(
        select(Bid).where(Bid.lead_id == lead.id, Bid.property_id == property_id)
    )
    if bid is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found"
        )
    if bid.status != BidStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only withdraw pending bids",
        )
    bid.status = BidStatus.withdrawn
    await db.commit()
    return {"success": True}


@router.post("/{lead_id}/rematch", response_model=RematchResponse)
async def rematch(
    lead_id: uuid.UUID,
    user: User = Depends(agent_dep),
    db: AsyncSession = Depends(get_db),
) -> RematchResponse:
    lead = await _get_owned_lead(lead_id, user, db)
    if lead.status != LeadStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only rematch active leads",
        )
    added = await match_properties_for_lead(lead, db, replace_existing=False)
    return RematchResponse(
        added_count=added,
        message=f"Added {added} new match{'es' if added != 1 else ''}",
    )
