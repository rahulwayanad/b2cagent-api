from fastapi import APIRouter

from app.schemas.catalog import PrivacyTypeOut, PropertyTypeOut
from app.services.catalog import PRIVACY_TYPE_CATALOG, PROPERTY_TYPE_CATALOG

router = APIRouter(tags=["catalog"])


@router.get("/property-types", response_model=list[PropertyTypeOut])
async def list_property_types() -> list[dict]:
    return PROPERTY_TYPE_CATALOG


@router.get("/privacy-types", response_model=list[PrivacyTypeOut])
async def list_privacy_types() -> list[dict]:
    return PRIVACY_TYPE_CATALOG
