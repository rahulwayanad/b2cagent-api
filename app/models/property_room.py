from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPKMixin

if TYPE_CHECKING:
    from app.models.property import Property


class PropertyRoom(UUIDPKMixin, Base):
    __tablename__ = "property_rooms"

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_type: Mapped[str] = mapped_column(String(128), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    property: Mapped["Property"] = relationship("Property", back_populates="rooms")

    def __repr__(self) -> str:
        return (
            f"<PropertyRoom id={self.id} property_id={self.property_id} "
            f"type={self.room_type!r} capacity={self.capacity} count={self.count}>"
        )
