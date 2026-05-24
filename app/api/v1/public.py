"""Public, unauthenticated read endpoints for shareable resources.

These are intentionally narrow: only properties currently marked `active` are
returned, and only fields safe for a public listing page. No bid, booking, or
manager-internal data leaks out here."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import Property, PropertyStatus
from app.schemas.property import PropertyAvailableDetailOut

router = APIRouter(prefix="/public", tags=["public"])


@router.get(
    "/properties/{property_id}",
    response_model=PropertyAvailableDetailOut,
)
async def get_public_property(
    property_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PropertyAvailableDetailOut:
    """Shareable property detail. Only active listings are visible."""
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
