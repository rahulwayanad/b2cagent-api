from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum as SAEnum, Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import UserRole
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.bid import Bid
    from app.models.property import Property


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"),
        nullable=False,
    )
    active_role: Mapped[UserRole | None] = mapped_column(
        SAEnum(UserRole, name="user_role"),
        nullable=True,
    )
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True, index=True)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    default_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_location: Mapped[str | None] = mapped_column(String(512), nullable=True)

    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    properties: Mapped[list["Property"]] = relationship(
        "Property",
        back_populates="manager",
        cascade="all, delete-orphan",
    )
    bids: Mapped[list["Bid"]] = relationship(
        "Bid",
        back_populates="agent",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role.value}>"
