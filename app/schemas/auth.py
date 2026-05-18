import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models import UserRole


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    phone: str | None = None
    phone_verified: bool
    email_verified: bool
    created_at: datetime


class CheckUserIn(BaseModel):
    identifier: str = Field(..., min_length=3, max_length=255)


class CheckUserOut(BaseModel):
    exists: bool


class RegisterIn(BaseModel):
    identifier: str = Field(..., min_length=3, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    role: UserRole
    email: EmailStr
    phone: str = Field(..., min_length=5, max_length=32)
    default_lat: float = Field(..., ge=-90, le=90)
    default_lng: float = Field(..., ge=-180, le=180)
    default_location: str | None = Field(None, max_length=512)


class RegisterOut(BaseModel):
    success: bool = True
    message: str = "OTP sent to your email"


class OTPSendIn(BaseModel):
    identifier: str = Field(..., min_length=3, max_length=255)


class OTPSendOut(BaseModel):
    success: bool = True
    message: str = "OTP sent"


class OTPVerifyIn(BaseModel):
    identifier: str = Field(..., min_length=3, max_length=255)
    otp: str = Field(..., min_length=6, max_length=6)


class AuthUserOut(BaseModel):
    id: uuid.UUID
    name: str
    email: EmailStr


class OTPVerifyOut(BaseModel):
    success: bool = True
    token: str
    user: AuthUserOut
    role: str
    roles: list[str]
    active_role: str
