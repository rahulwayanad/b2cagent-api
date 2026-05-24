import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.models import UserRole


class MeOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    roles: list[str]
    active_role: str | None
    phone: str | None = None
    phone_verified: bool
    email_verified: bool
    default_lat: float | None = None
    default_lng: float | None = None
    default_location: str | None = None
    avatar_url: str | None = None
    created_at: datetime


class AddRoleIn(BaseModel):
    role: Literal["agent", "manager"]


class AddRoleOut(BaseModel):
    success: bool = True
    roles: list[str]
    active_role: str | None
    message: str


class SwitchRoleIn(BaseModel):
    active_role: Literal["agent", "manager"]


class SwitchRoleOut(BaseModel):
    success: bool = True
    active_role: str


class MeUpdateIn(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=255)
    phone: str | None = Field(None, min_length=5, max_length=32)
    default_lat: float | None = Field(None, ge=-90, le=90)
    default_lng: float | None = Field(None, ge=-180, le=180)
    default_location: str | None = Field(None, max_length=512)
