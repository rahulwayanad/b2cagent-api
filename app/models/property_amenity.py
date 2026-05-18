from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPKMixin

if TYPE_CHECKING:
    from app.models.property import Property


class PropertyAmenity(UUIDPKMixin, Base):
    __tablename__ = "property_amenities"

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    icon_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    property: Mapped["Property"] = relationship("Property", back_populates="amenities")

    def __repr__(self) -> str:
        return (
            f"<PropertyAmenity id={self.id} property_id={self.property_id} "
            f"name={self.name!r}>"
        )
