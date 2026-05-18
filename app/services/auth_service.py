import secrets
from dataclasses import dataclass

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_pre_auth_token
from app.models import User, UserRole
from app.services.google_oauth import GoogleOAuthClient, GoogleUserInfo
from app.services.notifications import EmailSender, SMSSender


def _email_otp_key(user_id) -> str:
    return f"otp:{user_id}"


def _phone_otp_key(user_id) -> str:
    return f"phone_otp:{user_id}"


def _generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


@dataclass(frozen=True)
class CallbackResult:
    user: User
    pre_auth_token: str


@dataclass(frozen=True)
class VerifyOTPResult:
    user: User
    access_token: str
    requires_phone_verification: bool


class AuthService:
    def __init__(
        self,
        db: AsyncSession,
        redis: Redis,
        google_client: GoogleOAuthClient,
        email_sender: EmailSender,
        sms_sender: SMSSender,
    ) -> None:
        self.db = db
        self.redis = redis
        self.google_client = google_client
        self.email_sender = email_sender
        self.sms_sender = sms_sender

    async def handle_google_callback(
        self, *, code: str, role: UserRole
    ) -> CallbackResult:
        access_token = await self.google_client.exchange_code(code)
        info = await self.google_client.fetch_userinfo(access_token)
        user = await self._upsert_user(info=info, role=role)
        token = create_pre_auth_token(
            sub=str(user.id), role=user.role.value, email=user.email
        )
        return CallbackResult(user=user, pre_auth_token=token)

    async def login_with_contact(
        self, *, email: str | None = None, phone: str | None = None
    ) -> CallbackResult:
        if not email and not phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="email or phone is required",
            )

        user = None
        if phone:
            user = await self.db.scalar(select(User).where(User.phone == phone))
        if user is None and email:
            user = await self.db.scalar(select(User).where(User.email == email))

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="user not found",
            )

        token = create_pre_auth_token(
            sub=str(user.id), role=user.role.value, email=user.email
        )

        if phone:
            await self.send_phone_otp(user=user, phone=phone)
        else:
            await self.send_email_otp(user=user)

        return CallbackResult(user=user, pre_auth_token=token)

    async def signup_user(
        self,
        *,
        full_name: str,
        email: str,
        role: UserRole,
        phone: str | None = None,
    ) -> CallbackResult:
        existing = await self.db.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="email already exists",
            )
        if phone:
            existing_phone = await self.db.scalar(select(User).where(User.phone == phone))
            if existing_phone is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="phone already exists",
                )

        user = User(
            email=email,
            full_name=full_name,
            role=role,
            google_sub=None,
            phone=phone,
            phone_verified=False,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        token = create_pre_auth_token(
            sub=str(user.id), role=user.role.value, email=user.email
        )
        await self.send_email_otp(user=user)
        return CallbackResult(user=user, pre_auth_token=token)

    async def _upsert_user(self, *, info: GoogleUserInfo, role: UserRole) -> User:
        existing = await self.db.scalar(
            select(User).where(User.google_sub == info.sub)
        )
        if existing is None:
            existing = await self.db.scalar(
                select(User).where(User.email == info.email)
            )
        if existing is not None:
            existing.email = info.email
            existing.full_name = info.name
            existing.google_sub = info.sub
            user = existing
        else:
            user = User(
                email=info.email,
                full_name=info.name,
                google_sub=info.sub,
                role=role,
            )
            self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def send_email_otp(self, *, user: User) -> None:
        code = _generate_otp()
        await self.redis.set(
            _email_otp_key(user.id), code, ex=settings.OTP_TTL_SECONDS
        )
        await self.email_sender.send(
            to=user.email,
            subject="Your b2cagent verification code",
            body=(
                f"Hi {user.full_name},\n\n"
                f"Your verification code is: {code}\n"
                f"It expires in {settings.OTP_TTL_SECONDS // 60} minutes.\n"
            ),
        )

    async def verify_email_otp(self, *, user: User, code: str) -> VerifyOTPResult:
        key = _email_otp_key(user.id)
        stored = await self.redis.get(key)
        if stored is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="otp expired or not found",
            )
        if not secrets.compare_digest(stored, code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid otp",
            )
        await self.redis.delete(key)
        token = create_access_token(
            sub=str(user.id), role=user.role.value, email=user.email
        )
        requires_phone = (
            user.role == UserRole.manager and not user.phone_verified
        )
        return VerifyOTPResult(
            user=user,
            access_token=token,
            requires_phone_verification=requires_phone,
        )

    async def send_phone_otp(self, *, user: User, phone: str) -> None:
        user.phone = phone
        user.phone_verified = False
        await self.db.commit()
        await self.db.refresh(user)
        code = _generate_otp()
        await self.redis.set(
            _phone_otp_key(user.id), code, ex=settings.OTP_TTL_SECONDS
        )
        await self.sms_sender.send(
            to=phone,
            body=f"Your b2cagent phone verification code is {code}",
        )

    async def verify_phone_otp(self, *, user: User, code: str) -> User:
        key = _phone_otp_key(user.id)
        stored = await self.redis.get(key)
        if stored is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="phone otp expired or not found",
            )
        if not secrets.compare_digest(stored, code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid phone otp",
            )
        await self.redis.delete(key)
        user.phone_verified = True
        await self.db.commit()
        await self.db.refresh(user)
        return user
