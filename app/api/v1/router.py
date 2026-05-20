from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    bid_payments,
    bids,
    bookings,
    catalog,
    leads,
    properties,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(leads.router)
# bids router must be included BEFORE properties so /properties/available
# matches there rather than being parsed as /properties/{property_id}.
api_router.include_router(bids.router)
api_router.include_router(bid_payments.router)
api_router.include_router(bookings.router)
api_router.include_router(properties.router)
api_router.include_router(catalog.router)
api_router.include_router(admin.router)


@api_router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
