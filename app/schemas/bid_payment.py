import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models import PaymentMethod, PaymentStatus


class BidPaymentCreateIn(BaseModel):
    # Online is reserved for a later gateway integration. Only "cash" is
    # accepted today; sending "online" returns 501 from the endpoint.
    method: Literal["cash", "online"] = "cash"
    notes: str | None = None


class BidPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    bid_id: uuid.UUID
    method: PaymentMethod
    status: PaymentStatus
    amount: Decimal
    confirmed_at: datetime | None
    notes: str | None
    created_at: datetime


# Nested summary embedded in bid list responses so the UI can branch
# between "Mark paid" / "Awaiting confirmation" / "Booking created" without
# a second request per row.
class BidPaymentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    method: PaymentMethod
    status: PaymentStatus
    confirmed_at: datetime | None
