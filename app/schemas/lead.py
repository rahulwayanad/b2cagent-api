import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import BidStatus, LeadStatus


class LeadCreate(BaseModel):
    customer_name: str = Field(..., min_length=2, max_length=200)
    customer_email: EmailStr | None = None
    customer_phone: str | None = Field(None, min_length=5, max_length=20)
    customer_location_text: str | None = Field(None, max_length=512)
    customer_lat: float | None = None
    customer_lng: float | None = None
    check_in: date
    check_out: date
    adults: int = Field(1, ge=1, le=50)
    children: int = Field(0, ge=0, le=50)
    budget_min: Decimal | None = Field(None, ge=0)
    budget_max: Decimal | None = Field(None, ge=0)
    special_requirements: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate(self):
        if self.check_out < self.check_in:
            raise ValueError("check_out must be on or after check_in")
        if (
            self.budget_min is not None
            and self.budget_max is not None
            and self.budget_max < self.budget_min
        ):
            raise ValueError("budget_max must be >= budget_min")
        if not (self.customer_email or self.customer_phone):
            raise ValueError("at least one of customer_email or customer_phone required")
        return self


class LeadUpdate(BaseModel):
    customer_name: str | None = Field(None, min_length=2, max_length=200)
    customer_email: EmailStr | None = None
    customer_phone: str | None = Field(None, min_length=5, max_length=20)
    customer_location_text: str | None = Field(None, max_length=512)
    customer_lat: float | None = None
    customer_lng: float | None = None
    check_in: date | None = None
    check_out: date | None = None
    adults: int | None = Field(None, ge=1, le=50)
    children: int | None = Field(None, ge=0, le=50)
    budget_min: Decimal | None = Field(None, ge=0)
    budget_max: Decimal | None = Field(None, ge=0)
    notes: str | None = None
    special_requirements: str | None = None

    @model_validator(mode="after")
    def _validate(self):
        if (
            self.check_in is not None
            and self.check_out is not None
            and self.check_out < self.check_in
        ):
            raise ValueError("check_out must be on or after check_in")
        if (
            self.budget_min is not None
            and self.budget_max is not None
            and self.budget_max < self.budget_min
        ):
            raise ValueError("budget_max must be >= budget_min")
        return self


class LeadStatusUpdate(BaseModel):
    status: Literal["lost"]


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    customer_name: str
    customer_email: str | None
    customer_phone: str | None
    customer_location_text: str | None = None
    customer_lat: float | None = None
    customer_lng: float | None = None
    check_in: date
    check_out: date
    is_single_day: bool
    adults: int
    children: int
    budget_min: Decimal | None
    budget_max: Decimal | None
    special_requirements: str | None
    notes: str | None
    status: LeadStatus
    matched_properties_count: int = 0
    bids_count: int = 0
    created_at: datetime


class LeadListResponse(BaseModel):
    items: list[LeadResponse]
    total: int
    page: int
    limit: int


class BidSummary(BaseModel):
    id: uuid.UUID
    amount: Decimal
    status: BidStatus


class _AmenityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    icon_key: str | None = None


class _PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    url: str
    is_primary: bool


class _RoomSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    room_type: str
    capacity: int
    count: int


class MatchedPropertyResponse(BaseModel):
    property_id: uuid.UUID
    name: str
    location_text: str | None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    lat: float | None = None
    lng: float | None = None
    property_type: str | None
    b2c_rate: Decimal
    b2b_rate: Decimal
    photos: list[_PhotoOut]
    amenities: list[_AmenityOut]
    room_summary: list[_RoomSummary]
    match_score: int
    is_hidden: bool
    existing_bid: BidSummary | None = None


class MatchedPropertyListResponse(BaseModel):
    items: list[MatchedPropertyResponse]
    total: int
    page: int
    limit: int


class PlaceBidIn(BaseModel):
    amount: Decimal = Field(..., gt=0)


class BidResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    lead_id: uuid.UUID
    property_id: uuid.UUID
    check_in: date
    check_out: date
    amount: Decimal
    status: BidStatus
    created_at: datetime


class RematchResponse(BaseModel):
    added_count: int
    message: str
