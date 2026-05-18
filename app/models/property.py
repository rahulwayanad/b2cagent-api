from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum, Float, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import PrivacyType, PropertyStatus, PropertyType
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.bid import Bid
    from app.models.property_amenity import PropertyAmenity
    from app.models.property_photo import PropertyPhoto
    from app.models.property_room import PropertyRoom
    from app.models.user import User


class Property(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "properties"

    manager_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[PropertyStatus] = mapped_column(
        SAEnum(PropertyStatus, name="property_status"),
        nullable=False,
        default=PropertyStatus.active,
    )
    b2b_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    b2c_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    property_type: Mapped[PropertyType | None] = mapped_column(
        SAEnum(PropertyType, name="property_type"), nullable=True
    )
    privacy_type: Mapped[PrivacyType | None] = mapped_column(
        SAEnum(PrivacyType, name="privacy_type"), nullable=True
    )
    guests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    beds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_guests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_guests: Mapped[int | None] = mapped_column(Integer, nullable=True)

    manager: Mapped["User"] = relationship("User", back_populates="properties")
    rooms: Mapped[list["PropertyRoom"]] = relationship(
        "PropertyRoom",
        back_populates="property",
        cascade="all, delete-orphan",
    )
    amenities: Mapped[list["PropertyAmenity"]] = relationship(
        "PropertyAmenity",
        back_populates="property",
        cascade="all, delete-orphan",
    )
    photos: Mapped[list["PropertyPhoto"]] = relationship(
        "PropertyPhoto",
        back_populates="property",
        cascade="all, delete-orphan",
    )
    bids: Mapped[list["Bid"]] = relationship(
        "Bid",
        back_populates="property",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Property id={self.id} name={self.name!r} status={self.status.value}>"
