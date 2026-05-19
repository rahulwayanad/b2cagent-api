import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import require_active_role
from app.models import (
    Booking,
    BookingStatus,
    Property,
    PropertyAmenity,
    PropertyAvailabilityBlock,
    PropertyDayPrice,
    PropertyPhoto,
    PropertyRoom,
    PropertyStatus,
    User,
    UserRole,
)
from app.schemas.booking import BlockCreate, BlockOut, BookingOut
from app.schemas.property import (
    AmenityCreate,
    AmenityOut,
    DayPriceOut,
    DayPriceUpsert,
    PhotoOut,
    PropertyCreate,
    PropertyDetailOut,
    PropertyListOut,
    PropertyOut,
    PropertyUpdate,
    RoomCreate,
    RoomOut,
)
from app.services.field_config_service import get_disabled_fields
from app.services.storage_service import Storage, build_photo_key, get_storage

router = APIRouter(prefix="/properties", tags=["properties"])

manager_dep = require_active_role(UserRole.manager)


async def _reject_disabled(
    db: AsyncSession, entity: str, payload: dict
) -> None:
    """Raise 422 if the request tries to set any field the super admin disabled."""
    disabled = await get_disabled_fields(db, entity)
    rejected = sorted(
        k for k, v in payload.items() if k in disabled and v is not None
    )
    if rejected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "fields disabled by super admin",
                "fields": rejected,
            },
        )


async def get_owned_property(
    property_id: uuid.UUID,
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
) -> Property:
    prop = await db.get(Property, property_id)
    if prop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="property not found",
        )
    if prop.manager_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not own this property",
        )
    return prop


IDEM_KEY_PREFIX = "idem:property:"
IDEM_KEY_TTL = 60 * 60 * 24  # 24h


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PropertyOut)
async def create_property(
    payload: PropertyCreate,
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Property:
    # Replay: same key → return the already-created property.
    if idempotency_key:
        cached_id = await redis.get(f"{IDEM_KEY_PREFIX}{idempotency_key}")
        if cached_id:
            existing = await db.get(Property, uuid.UUID(cached_id))
            if existing is not None and existing.manager_id == user.id:
                return existing

    data = payload.model_dump(exclude_unset=True)
    await _reject_disabled(db, "property", data)
    prop = Property(
        manager_id=user.id,
        status=PropertyStatus.draft,
        **data,
    )
    db.add(prop)
    await db.commit()
    await db.refresh(prop)

    if idempotency_key:
        await redis.set(
            f"{IDEM_KEY_PREFIX}{idempotency_key}",
            str(prop.id),
            ex=IDEM_KEY_TTL,
        )

    return prop


@router.post("/{property_id}/publish", response_model=PropertyOut)
async def publish_property(
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> Property:
    if prop.status != PropertyStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot publish property in status={prop.status.value}",
        )
    # Sanity checks: enough info to be useful to agents.
    photo_count = await db.scalar(
        select(func.count(PropertyPhoto.id)).where(
            PropertyPhoto.property_id == prop.id
        )
    )
    room_count = await db.scalar(
        select(func.count(PropertyRoom.id)).where(
            PropertyRoom.property_id == prop.id
        )
    )
    missing: list[str] = []
    if prop.b2b_rate is None or prop.b2b_rate <= 0:
        missing.append("B2B rate")
    if prop.b2c_rate is None or prop.b2c_rate <= 0:
        missing.append("B2C rate")
    if not photo_count:
        missing.append("at least one photo")
    if not room_count:
        missing.append("at least one room")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Add {', '.join(missing)} before publishing",
        )

    prop.status = PropertyStatus.active
    await db.commit()
    await db.refresh(prop)
    return prop


class _SetActiveIn(BaseModel):
    active: bool


@router.post("/{property_id}/set-active", response_model=PropertyOut)
async def set_property_active(
    payload: _SetActiveIn,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> Property:
    """Toggle between active and inactive. Allowed only from one of those two
    states (or from inactive→active when previously draft is not allowed)."""
    if prop.status not in (PropertyStatus.active, PropertyStatus.inactive):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot toggle active/inactive from status={prop.status.value}",
        )
    prop.status = PropertyStatus.active if payload.active else PropertyStatus.inactive
    await db.commit()
    await db.refresh(prop)
    return prop


@router.get("", response_model=PropertyListOut)
async def list_properties(
    status_filter: PropertyStatus | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
) -> PropertyListOut:
    base = select(Property).where(Property.manager_id == user.id)
    if status_filter is not None:
        base = base.where(Property.status == status_filter)

    total = await db.scalar(
        select(func.count()).select_from(base.subquery())
    )
    items_query = (
        base.options(selectinload(Property.rooms))
        .order_by(Property.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = (await db.scalars(items_query)).all()
    return PropertyListOut(
        items=[_property_to_out(p) for p in items],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


def _room_totals(prop: Property) -> tuple[int, int]:
    """Sum (room_count, sleeps_count) across the property's PropertyRoom rows."""
    rooms = prop.rooms
    room_count = sum(r.count or 0 for r in rooms)
    sleeps_count = sum((r.capacity or 0) * (r.count or 0) for r in rooms)
    return room_count, sleeps_count


def _property_to_out(prop: Property) -> PropertyOut:
    room_count, sleeps_count = _room_totals(prop)
    return PropertyOut.model_validate(prop).model_copy(
        update={"room_count": room_count, "sleeps_count": sleeps_count}
    )


@router.get("/{property_id}", response_model=PropertyDetailOut)
async def get_property(
    property_id: uuid.UUID,
    user: User = Depends(manager_dep),
    db: AsyncSession = Depends(get_db),
) -> PropertyDetailOut:
    result = await db.execute(
        select(Property)
        .where(Property.id == property_id)
        .options(
            selectinload(Property.rooms),
            selectinload(Property.amenities),
            selectinload(Property.photos),
        )
    )
    prop = result.scalar_one_or_none()
    if prop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="property not found"
        )
    if prop.manager_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not own this property",
        )
    room_count, sleeps_count = _room_totals(prop)
    return PropertyDetailOut.model_validate(prop).model_copy(
        update={"room_count": room_count, "sleeps_count": sleeps_count}
    )


@router.patch("/{property_id}", response_model=PropertyOut)
async def update_property(
    payload: PropertyUpdate,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> Property:
    updates = payload.model_dump(exclude_unset=True)
    await _reject_disabled(db, "property", updates)
    for field, value in updates.items():
        setattr(prop, field, value)
    await db.commit()
    await db.refresh(prop)
    return prop


@router.post(
    "/{property_id}/close", response_model=PropertyOut
)
async def close_property(
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> Property:
    if prop.status != PropertyStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"cannot close property in status={prop.status.value}",
        )
    prop.status = PropertyStatus.booked
    await db.commit()
    await db.refresh(prop)
    return prop


# ---- rooms -----------------------------------------------------------------


@router.post(
    "/{property_id}/rooms",
    status_code=status.HTTP_201_CREATED,
    response_model=RoomOut,
)
async def add_room(
    payload: RoomCreate,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> PropertyRoom:
    room = PropertyRoom(property_id=prop.id, **payload.model_dump())
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


@router.delete(
    "/{property_id}/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_room(
    room_id: uuid.UUID,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> Response:
    room = await db.scalar(
        select(PropertyRoom).where(
            PropertyRoom.id == room_id, PropertyRoom.property_id == prop.id
        )
    )
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="room not found"
        )
    await db.delete(room)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- amenities -------------------------------------------------------------


@router.post(
    "/{property_id}/amenities",
    status_code=status.HTTP_201_CREATED,
    response_model=AmenityOut,
)
async def add_amenity(
    payload: AmenityCreate,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> PropertyAmenity:
    amenity = PropertyAmenity(property_id=prop.id, **payload.model_dump())
    db.add(amenity)
    await db.commit()
    await db.refresh(amenity)
    return amenity


@router.delete(
    "/{property_id}/amenities/{amenity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_amenity(
    amenity_id: uuid.UUID,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> Response:
    amenity = await db.scalar(
        select(PropertyAmenity).where(
            PropertyAmenity.id == amenity_id,
            PropertyAmenity.property_id == prop.id,
        )
    )
    if amenity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="amenity not found"
        )
    await db.delete(amenity)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- photos ----------------------------------------------------------------


@router.post(
    "/{property_id}/photos",
    status_code=status.HTTP_201_CREATED,
    response_model=PhotoOut,
)
async def upload_photo(
    file: UploadFile = File(...),
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> PropertyPhoto:
    content_type = file.content_type or ""
    # Read up to cap+1 to detect oversize without buffering arbitrary data.
    data = await file.read(settings.MAX_PHOTO_SIZE_BYTES + 1)
    if len(data) > settings.MAX_PHOTO_SIZE_BYTES:
        limit_mb = settings.MAX_PHOTO_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Photo exceeds the {limit_mb} MB limit",
        )
    key = build_photo_key(property_id=prop.id, content_type=content_type)
    url = await storage.upload(key=key, data=data, content_type=content_type)

    max_order = await db.scalar(
        select(func.coalesce(func.max(PropertyPhoto.sort_order), -1)).where(
            PropertyPhoto.property_id == prop.id
        )
    )
    existing_count = await db.scalar(
        select(func.count()).select_from(
            select(PropertyPhoto.id)
            .where(PropertyPhoto.property_id == prop.id)
            .subquery()
        )
    )
    photo = PropertyPhoto(
        property_id=prop.id,
        url=url,
        is_primary=(existing_count == 0),
        sort_order=(max_order or 0) + 1,
    )
    db.add(photo)
    await db.commit()
    await db.refresh(photo)
    return photo


@router.delete(
    "/{property_id}/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_photo(
    photo_id: uuid.UUID,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    photo = await db.scalar(
        select(PropertyPhoto).where(
            PropertyPhoto.id == photo_id,
            PropertyPhoto.property_id == prop.id,
        )
    )
    if photo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="photo not found"
        )
    was_primary = photo.is_primary
    url = photo.url
    await db.delete(photo)
    await db.commit()
    await storage.delete(url=url)

    if was_primary:
        # promote the next photo (lowest sort_order) to primary
        next_photo = await db.scalar(
            select(PropertyPhoto)
            .where(PropertyPhoto.property_id == prop.id)
            .order_by(PropertyPhoto.sort_order.asc())
            .limit(1)
        )
        if next_photo is not None:
            next_photo.is_primary = True
            await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{property_id}/photos/{photo_id}/primary", response_model=PhotoOut
)
async def set_primary_photo(
    photo_id: uuid.UUID,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> PropertyPhoto:
    photo = await db.scalar(
        select(PropertyPhoto).where(
            PropertyPhoto.id == photo_id,
            PropertyPhoto.property_id == prop.id,
        )
    )
    if photo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="photo not found"
        )
    # Single-statement flip so only the target ends up primary, no matter how
    # many rows currently have is_primary=True.
    await db.execute(
        update(PropertyPhoto)
        .where(PropertyPhoto.property_id == prop.id)
        .values(is_primary=False)
    )
    photo.is_primary = True
    await db.commit()
    await db.refresh(photo)
    return photo


# ---- bookings (read-only for managers) ------------------------------------


@router.get("/{property_id}/bookings", response_model=list[BookingOut])
async def list_bookings(
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> list[BookingOut]:
    result = await db.execute(
        select(Booking)
        .where(Booking.property_id == prop.id)
        .order_by(Booking.check_in.asc())
    )
    return [BookingOut.model_validate(b) for b in result.scalars().all()]


# ---- availability blocks --------------------------------------------------


@router.get("/{property_id}/blocks", response_model=list[BlockOut])
async def list_blocks(
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> list[BlockOut]:
    result = await db.execute(
        select(PropertyAvailabilityBlock)
        .where(PropertyAvailabilityBlock.property_id == prop.id)
        .order_by(PropertyAvailabilityBlock.start_date.asc())
    )
    return [BlockOut.model_validate(b) for b in result.scalars().all()]


@router.post(
    "/{property_id}/blocks",
    status_code=status.HTTP_201_CREATED,
    response_model=BlockOut,
)
async def create_block(
    payload: BlockCreate,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> BlockOut:
    overlapping_booking = await db.scalar(
        select(Booking).where(
            Booking.property_id == prop.id,
            Booking.status == BookingStatus.active,
            Booking.check_in <= payload.end_date,
            Booking.check_out >= payload.start_date,
        )
    )
    if overlapping_booking is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A booking already exists in this date range",
        )
    block = PropertyAvailabilityBlock(
        property_id=prop.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason,
    )
    db.add(block)
    await db.commit()
    await db.refresh(block)
    return BlockOut.model_validate(block)


@router.delete(
    "/{property_id}/blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_block(
    block_id: uuid.UUID,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> Response:
    block = await db.scalar(
        select(PropertyAvailabilityBlock).where(
            PropertyAvailabilityBlock.id == block_id,
            PropertyAvailabilityBlock.property_id == prop.id,
        )
    )
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="block not found"
        )
    await db.delete(block)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- per-day price overrides ----------------------------------------------


@router.get(
    "/{property_id}/day-prices", response_model=list[DayPriceOut]
)
async def list_day_prices(
    start: str = Query(..., description="YYYY-MM-DD inclusive"),
    end: str = Query(..., description="YYYY-MM-DD inclusive"),
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> list[DayPriceOut]:
    from datetime import date as _date

    try:
        start_d = _date.fromisoformat(start)
        end_d = _date.fromisoformat(end)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid date: {e}",
        ) from e
    if end_d < start_d:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end must be on or after start",
        )
    rows = (
        await db.scalars(
            select(PropertyDayPrice)
            .where(
                PropertyDayPrice.property_id == prop.id,
                PropertyDayPrice.date >= start_d,
                PropertyDayPrice.date <= end_d,
            )
            .order_by(PropertyDayPrice.date.asc())
        )
    ).all()
    return [DayPriceOut.model_validate(r) for r in rows]


@router.put(
    "/{property_id}/day-prices/{day}", response_model=DayPriceOut
)
async def upsert_day_price(
    day: str,
    payload: DayPriceUpsert,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> DayPriceOut:
    from datetime import date as _date

    try:
        d = _date.fromisoformat(day)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid date: {e}",
        ) from e
    existing = await db.scalar(
        select(PropertyDayPrice).where(
            PropertyDayPrice.property_id == prop.id,
            PropertyDayPrice.date == d,
        )
    )
    if existing is None:
        existing = PropertyDayPrice(
            property_id=prop.id,
            date=d,
            b2b_rate=payload.b2b_rate,
            b2c_rate=payload.b2c_rate,
        )
        db.add(existing)
    else:
        existing.b2b_rate = payload.b2b_rate
        existing.b2c_rate = payload.b2c_rate
    await db.commit()
    await db.refresh(existing)
    return DayPriceOut.model_validate(existing)


@router.delete(
    "/{property_id}/day-prices/{day}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_day_price(
    day: str,
    prop: Property = Depends(get_owned_property),
    db: AsyncSession = Depends(get_db),
) -> Response:
    from datetime import date as _date

    try:
        d = _date.fromisoformat(day)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid date: {e}",
        ) from e
    row = await db.scalar(
        select(PropertyDayPrice).where(
            PropertyDayPrice.property_id == prop.id,
            PropertyDayPrice.date == d,
        )
    )
    if row is not None:
        await db.delete(row)
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
