from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, user_roles
from app.models import User, UserRole
from app.schemas.user import (
    AddRoleIn,
    AddRoleOut,
    MeOut,
    MeUpdateIn,
    SwitchRoleIn,
    SwitchRoleOut,
)

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
        created_at=user.created_at,
    )


@router.get("/me", response_model=MeOut)
async def get_me(user: User = Depends(get_current_user)) -> MeOut:
    return _to_me_out(user)


@router.patch("/me", response_model=MeOut)
async def update_me(
    payload: MeUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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
