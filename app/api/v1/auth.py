from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import create_access_token, get_current_user, user_roles
from app.models import User, UserRole
from app.schemas.auth import (
    AuthUserOut,
    CheckUserIn,
    CheckUserOut,
    OTPSendIn,
    OTPSendOut,
    OTPVerifyIn,
    OTPVerifyOut,
    RegisterIn,
    RegisterOut,
    UserOut,
)
from app.services.email_template_service import send_templated_email
from app.services.notifications import EmailSender, get_email_sender
from app.services.otp_service import OTPService

router = APIRouter(prefix="/auth", tags=["auth"])


def _is_email(identifier: str) -> bool:
    return "@" in identifier


def get_otp_service(
    redis: Redis = Depends(get_redis),
    email_sender: EmailSender = Depends(get_email_sender),
) -> OTPService:
    return OTPService(redis=redis, email_sender=email_sender)


async def _find_user(db: AsyncSession, identifier: str) -> User | None:
    if _is_email(identifier):
        return await db.scalar(select(User).where(User.email == identifier))
    return await db.scalar(select(User).where(User.phone == identifier))


@router.post("/check", response_model=CheckUserOut)
async def check_user(
    payload: CheckUserIn,
    db: AsyncSession = Depends(get_db),
) -> CheckUserOut:
    user = await _find_user(db, payload.identifier)
    return CheckUserOut(exists=user is not None)


@router.post("/register", response_model=RegisterOut)
async def register(
    payload: RegisterIn,
    db: AsyncSession = Depends(get_db),
    otp_service: OTPService = Depends(get_otp_service),
) -> RegisterOut:
    if payload.role not in (UserRole.agent, UserRole.manager):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="role must be 'agent' or 'manager'",
        )

    existing_email = await db.scalar(select(User).where(User.email == payload.email))
    if existing_email is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    existing_phone = await db.scalar(select(User).where(User.phone == payload.phone))
    if existing_phone is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phone already registered",
        )

    user = User(
        email=payload.email,
        phone=payload.phone,
        full_name=payload.name,
        role=payload.role,
        is_active=True,
        email_verified=False,
        default_lat=payload.default_lat,
        default_lng=payload.default_lng,
        default_location=payload.default_location,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await otp_service.send_email_otp(
        payload.email, str(user.id), db=db, name=user.full_name
    )
    return RegisterOut(success=True, message="OTP sent to your email")


@router.post("/otp/send", response_model=OTPSendOut)
async def otp_send(
    payload: OTPSendIn,
    db: AsyncSession = Depends(get_db),
    otp_service: OTPService = Depends(get_otp_service),
) -> OTPSendOut:
    user = await _find_user(db, payload.identifier)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    await otp_service.send_email_otp(
        user.email, str(user.id), db=db, name=user.full_name
    )
    return OTPSendOut(success=True, message="OTP sent")


@router.post("/otp/verify", response_model=OTPVerifyOut)
async def otp_verify(
    payload: OTPVerifyIn,
    db: AsyncSession = Depends(get_db),
    otp_service: OTPService = Depends(get_otp_service),
    email_sender: EmailSender = Depends(get_email_sender),
) -> OTPVerifyOut:
    user = await _find_user(db, payload.identifier)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await otp_service.verify_otp(str(user.id), payload.otp)

    is_first_verification = not user.email_verified
    user.email_verified = True

    roles = user_roles(user)
    if user.active_role is not None and user.active_role.value in roles:
        active_role = user.active_role.value
    else:
        active_role = roles[0]
        user.active_role = type(user.role)(active_role)

    await db.commit()
    await db.refresh(user)

    if is_first_verification:
        role_label = active_role
        role_action = (
            "listing properties and accepting bids"
            if role_label == "manager"
            else "finding properties for your customers"
        )
        try:
            await send_templated_email(
                db,
                email_sender,
                code="welcome",
                to=user.email,
                context={
                    "name": user.full_name,
                    "role": role_label,
                    "role_action": role_action,
                    "link_url": (
                        f"{settings.FRONTEND_BASE_URL.rstrip('/')}/dashboard"
                    ),
                },
            )
        except Exception:  # noqa: BLE001
            pass

    token = create_access_token(
        sub=str(user.id),
        role=user.role.value,
        email=user.email,
    )
    return OTPVerifyOut(
        success=True,
        token=token,
        user=AuthUserOut(id=user.id, name=user.full_name, email=user.email),
        role=user.role.value,
        roles=roles,
        active_role=active_role,
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)
