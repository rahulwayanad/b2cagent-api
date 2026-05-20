import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import BookingStatus


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    property_id: uuid.UUID
    lead_id: uuid.UUID | None
    bid_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    customer_name: str
    customer_email: str | None
    customer_phone: str | None
    check_in: date
    check_out: date
    guests: int
    amount: Decimal
    status: BookingStatus
    created_at: datetime


# Agent-facing — joined with property metadata so a single fetch is enough
# to render the bookings list and the lead-detail booking card.
class AgentBookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    property_id: uuid.UUID
    property_name: str
    property_location: str | None
    lead_id: uuid.UUID | None
    bid_id: uuid.UUID | None
    customer_name: str
    customer_email: str | None
    customer_phone: str | None
    check_in: date
    check_out: date
    guests: int
    # Per-night, matching bid.amount semantics. UI computes total = amount × nights.
    amount: Decimal
    status: BookingStatus
    created_at: datetime


class BlockCreate(BaseModel):
    start_date: date
    end_date: date
    reason: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _validate(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class BlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    property_id: uuid.UUID
    start_date: date
    end_date: date
    reason: str | None
    created_at: datetime
