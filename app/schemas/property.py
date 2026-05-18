import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import PrivacyType, PropertyStatus, PropertyType


class RoomCreate(BaseModel):
    room_type: str = Field(..., min_length=1, max_length=128)
    capacity: int = Field(..., ge=1)
    count: int = Field(..., ge=1)
    description: str | None = None


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    room_type: str
    capacity: int
    count: int
    description: str | None = None


class AmenityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    icon_key: str | None = Field(None, max_length=64)


class AmenityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    icon_key: str | None = None


class PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    url: str
    is_primary: bool
    sort_order: int


class _GuestBoundsMixin(BaseModel):
    @model_validator(mode="after")
    def _check_guest_bounds(self):
        if (
            self.min_guests is not None
            and self.max_guests is not None
            and self.min_guests > self.max_guests
        ):
            raise ValueError("min_guests cannot exceed max_guests")
        return self


class PropertyCreate(_GuestBoundsMixin):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    location_text: str | None = Field(None, max_length=512)
    lat: float | None = None
    lng: float | None = None
    b2b_rate: Decimal = Field(..., ge=0)
    b2c_rate: Decimal = Field(..., ge=0)

    property_type: PropertyType | None = None
    privacy_type: PrivacyType | None = None
    guests: int | None = Field(None, ge=1)
    bedrooms: int | None = Field(None, ge=0)
    beds: int | None = Field(None, ge=0)
    bathrooms: int | None = Field(None, ge=0)
    min_guests: int | None = Field(None, ge=1)
    max_guests: int | None = Field(None, ge=1)


class PropertyUpdate(_GuestBoundsMixin):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    location_text: str | None = Field(None, max_length=512)
    lat: float | None = None
    lng: float | None = None
    b2b_rate: Decimal | None = Field(None, ge=0)
    b2c_rate: Decimal | None = Field(None, ge=0)
    status: PropertyStatus | None = None

    property_type: PropertyType | None = None
    privacy_type: PrivacyType | None = None
    guests: int | None = Field(None, ge=1)
    bedrooms: int | None = Field(None, ge=0)
    beds: int | None = Field(None, ge=0)
    bathrooms: int | None = Field(None, ge=0)
    min_guests: int | None = Field(None, ge=1)
    max_guests: int | None = Field(None, ge=1)


class PropertyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    manager_id: uuid.UUID
    name: str
    description: str | None = None
    location_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    status: PropertyStatus
    b2b_rate: Decimal
    b2c_rate: Decimal
    property_type: PropertyType | None = None
    privacy_type: PrivacyType | None = None
    guests: int | None = None
    bedrooms: int | None = None
    beds: int | None = None
    bathrooms: int | None = None
    min_guests: int | None = None
    max_guests: int | None = None
    created_at: datetime
    updated_at: datetime


class PropertyDetailOut(PropertyOut):
    rooms: list[RoomOut] = []
    amenities: list[AmenityOut] = []
    photos: list[PhotoOut] = []


class PropertyListOut(BaseModel):
    items: list[PropertyOut]
    total: int
    limit: int
    offset: int


# Agent-facing views never include b2b_rate. Declaring it as a separate schema
# (rather than excluding at serialization time) keeps the OpenAPI shape honest.
class PropertyAvailableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    manager_id: uuid.UUID
    name: str
    description: str | None = None
    location_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    status: PropertyStatus
    b2c_rate: Decimal
    property_type: PropertyType | None = None
    privacy_type: PrivacyType | None = None
    guests: int | None = None
    bedrooms: int | None = None
    beds: int | None = None
    bathrooms: int | None = None
    min_guests: int | None = None
    max_guests: int | None = None
    created_at: datetime
    updated_at: datetime


class PropertyAvailableDetailOut(PropertyAvailableOut):
    rooms: list[RoomOut] = []
    amenities: list[AmenityOut] = []
    photos: list[PhotoOut] = []


class PropertyAvailableListOut(BaseModel):
    items: list[PropertyAvailableOut]
    total: int
    limit: int
    offset: int
