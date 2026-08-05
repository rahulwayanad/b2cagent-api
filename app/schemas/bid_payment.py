import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models import PaymentMethod, PaymentStatus


class InvoiceAddressIn(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    gstin: str | None = None
    line1: str | None = None
    city: str | None = None
    state: str | None = None
    pin_code: str | None = None


class BidPaymentCreateIn(BaseModel):
    # Online is reserved for a later gateway integration. Only "cash" is
    # accepted today; sending "online" returns 501 from the endpoint.
    method: Literal["cash", "online"] = "cash"
    notes: str | None = None
    invoice_address: InvoiceAddressIn | None = None
    # CSV of "email", "whatsapp". Frontend keeps WhatsApp disabled for v1.
    delivery_channels: list[Literal["email", "whatsapp"]] | None = None


class BidPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    bid_id: uuid.UUID
    method: PaymentMethod
    status: PaymentStatus
    amount: Decimal
    confirmed_at: datetime | None
    notes: str | None
    invoice_no: str | None = None
    created_at: datetime


# ---- Checkout-data DTO (GET /bids/{id}/checkout) -------------------------


class CheckoutManager(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    phone: str | None
    business_location: str | None


class CheckoutProperty(BaseModel):
    id: uuid.UUID
    name: str
    photo_url: str | None
    location_text: str | None
    bedrooms: int | None
    guests: int | None


class CheckoutLead(BaseModel):
    id: uuid.UUID
    customer_name: str
    customer_email: str | None
    customer_phone: str | None
    customer_location_text: str | None
    adults: int
    children: int


class CheckoutPricing(BaseModel):
    nights: int
    b2c_rate: Decimal
    b2b_rate: Decimal
    bid_amount: Decimal  # per-night
    bid_total: Decimal
    b2c_total: Decimal
    commission_amount: Decimal
    commission_rate: Decimal  # 0..1


class CheckoutDataOut(BaseModel):
    bid_id: uuid.UUID
    bid_status: str
    check_in: datetime
    check_out: datetime
    property: CheckoutProperty
    manager: CheckoutManager
    lead: CheckoutLead | None
    pricing: CheckoutPricing
    payment: BidPaymentOut | None  # existing payment if already initiated


# Nested summary embedded in bid list responses so the UI can branch
# between "Mark paid" / "Awaiting confirmation" / "Booking created" without
# a second request per row.
class BidPaymentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    method: PaymentMethod
    status: PaymentStatus
    confirmed_at: datetime | None
