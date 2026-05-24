from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, user_roles
from app.models import User, UserRole
from app.schemas.subscription import MySubscriptionOut
from app.schemas.user import (
    AddRoleIn,
    AddRoleOut,
    MeOut,
    MeUpdateIn,
    SwitchRoleIn,
    SwitchRoleOut,
)
from app.services.email_template_service import send_templated_email
from app.services.notifications import EmailSender, get_email_sender
from app.services.storage_service import Storage, build_avatar_key, get_storage
from app.services.subscription_service import my_subscription_summary

router = APIRouter(prefix="/users", tags=["users"])


def _to_me_out(user: User) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        roles=user_roles(user),
        active_role=user.active_role.value if user.active_role else None,
        phone=user.phone,
        phone_verified=user.phone_verified,
        email_verified=user.email_verified,
        default_lat=user.default_lat,
        default_lng=user.default_lng,
        default_location=user.default_location,
        avatar_url=user.avatar_url,
        created_at=user.created_at,
    )


@router.get("/me", response_model=MeOut)
async def get_me(user: User = Depends(get_current_user)) -> MeOut:
    return _to_me_out(user)


@router.get("/me/subscription", response_model=MySubscriptionOut)
async def get_my_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MySubscriptionOut:
    summary = await my_subscription_summary(user, db)
    return MySubscriptionOut.model_validate(summary)


@router.post("/me/avatar", response_model=MeOut)
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> MeOut:
    content_type = file.content_type or ""
    data = await file.read(settings.MAX_PHOTO_SIZE_BYTES + 1)
    if len(data) > settings.MAX_PHOTO_SIZE_BYTES:
        limit_mb = settings.MAX_PHOTO_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Photo exceeds the {limit_mb} MB limit",
        )
    key = build_avatar_key(user_id=user.id, content_type=content_type)
    url = await storage.upload(key=key, data=data, content_type=content_type)

    old_url = user.avatar_url
    user.avatar_url = url
    await db.commit()
    await db.refresh(user)

    # Best-effort cleanup of the prior avatar. Don't fail the request if the
    # backing storage can't delete (e.g. stale S3 perms).
    if old_url:
        try:
            await storage.delete(url=old_url)
        except Exception:  # noqa: BLE001
            pass

    return _to_me_out(user)


@router.delete("/me/avatar", response_model=MeOut)
async def delete_avatar(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> MeOut:
    old_url = user.avatar_url
    user.avatar_url = None
    await db.commit()
    await db.refresh(user)
    if old_url:
        try:
            await storage.delete(url=old_url)
        except Exception:  # noqa: BLE001
            pass
    return _to_me_out(user)


@router.patch("/me", response_model=MeOut)
async def update_me(
    payload: MeUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
) -> MeOut:
    updates = payload.model_dump(exclude_unset=True)

    if "phone" in updates and updates["phone"] != user.phone:
        existing = await db.scalar(
            select(User).where(User.phone == updates["phone"], User.id != user.id)
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Phone already in use",
            )

    for field, value in updates.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)

    if updates:
        try:
            role_for_link = (
                user.active_role.value if user.active_role else "agent"
            )
            await send_templated_email(
                db,
                email_sender,
                code="profile_updated",
                to=user.email,
                context={
                    "name": user.full_name,
                    "link_url": (
                        f"{settings.FRONTEND_BASE_URL.rstrip('/')}"
                        f"/{role_for_link}/profile"
                    ),
                },
            )
        except Exception:  # noqa: BLE001
            pass

    return _to_me_out(user)


@router.post("/me/add-role", response_model=AddRoleOut)
async def add_role(
    payload: AddRoleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AddRoleOut:
    requested = payload.role
    current = user.role

    if current == UserRole.both:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role already exists",
        )
    if current.value == requested:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role already exists",
        )
    if current not in (UserRole.agent, UserRole.manager):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"cannot add roles to user with role={current.value}",
        )

    user.role = UserRole.both
    if user.active_role is None:
        user.active_role = UserRole(requested)
    await db.commit()
    await db.refresh(user)

    label = "Manager role added" if requested == "manager" else "Agent role added"
    return AddRoleOut(
        success=True,
        roles=user_roles(user),
        active_role=user.active_role.value if user.active_role else None,
        message=label,
    )


@router.post("/me/switch-role", response_model=SwitchRoleOut)
async def switch_role(
    payload: SwitchRoleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SwitchRoleOut:
    requested = payload.active_role
    available = user_roles(user)
    if requested not in available:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have this role",
        )

    user.active_role = UserRole(requested)
    await db.commit()
    await db.refresh(user)
    return SwitchRoleOut(success=True, active_role=requested)
