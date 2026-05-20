import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models import User, UserRole


def user_roles(user: User) -> list[str]:
    """Expand role enum into a flat list.

    'both' and 'super_admin' both unlock manager + agent surfaces. Admins keep
    their elevated powers via the explicit super_admin role check at
    /admin/... endpoints; here we just let them operate either app.
    """
    if user.role in (UserRole.both, UserRole.super_admin):
        return [UserRole.agent.value, UserRole.manager.value]
    return [user.role.value]


def resolve_active_role(user: User, header_value: str | None) -> str:
    """Pick the active role for a request.

    Precedence: explicit header → stored active_role → single role.
    """
    available = user_roles(user)
    if header_value:
        if header_value not in available:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"user does not have role={header_value}",
            )
        return header_value
    if user.active_role is not None and user.active_role.value in available:
        return user.active_role.value
    if len(available) == 1:
        return available[0]
    return UserRole.agent.value  # both-role user with no header / stored pref

bearer_scheme = HTTPBearer(auto_error=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    *,
    sub: str,
    role: str,
    email: str,
    expires_minutes: int | None = None,
) -> str:
    payload = {
        "sub": sub,
        "role": role,
        "email": email,
        "iat": _now(),
        "exp": _now() + timedelta(minutes=expires_minutes or settings.JWT_EXPIRES_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_pre_auth_token(*, sub: str, role: str, email: str) -> str:
    payload = {
        "sub": sub,
        "role": role,
        "email": email,
        "pre_auth": True,
        "iat": _now(),
        "exp": _now() + timedelta(minutes=settings.PRE_AUTH_TOKEN_EXPIRES_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
        ) from exc


async def _load_user(db: AsyncSession, sub: str) -> User:
    try:
        user_id = uuid.UUID(sub)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid subject",
        ) from exc
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found or inactive",
        )
    return user


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    claims = decode_token(creds.credentials)
    if claims.get("pre_auth"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="full authentication required",
        )
    return await _load_user(db, claims["sub"])


async def get_pre_auth_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    claims = decode_token(creds.credentials)
    if not claims.get("pre_auth"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="pre-auth token required",
        )
    return await _load_user(db, claims["sub"])


def require_role(role: UserRole | str):
    role_value = role.value if isinstance(role, UserRole) else role

    async def _dep(user: User = Depends(get_current_user)) -> User:
        # super_admin passes any role check below super_admin itself;
        # require_role(super_admin) still needs an exact match.
        if (
            user.role.value != role_value
            and user.role != UserRole.both
            and not (
                user.role == UserRole.super_admin
                and role_value != UserRole.super_admin.value
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires {role_value} role",
            )
        return user

    return _dep


def require_active_role(role: UserRole | str):
    """Require that the request's X-Active-Role header matches the given role.

    The user must also actually hold that role (single match or 'both').
    """
    role_value = role.value if isinstance(role, UserRole) else role

    async def _dep(
        request: Request,
        user: User = Depends(get_current_user),
    ) -> User:
        active = resolve_active_role(user, request.headers.get("X-Active-Role"))
        if active != role_value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"active role must be {role_value} (currently {active})",
            )
        return user

    return _dep


async def get_active_role(
    request: Request,
    user: User = Depends(get_current_user),
) -> str:
    return resolve_active_role(user, request.headers.get("X-Active-Role"))
