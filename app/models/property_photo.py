from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPKMixin

if TYPE_CHECKING:
    from app.models.property import Property


class PropertyPhoto(UUIDPKMixin, Base):
    __tablename__ = "property_photos"

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    property: Mapped["Property"] = relationship("Property", back_populates="photos")

    def __repr__(self) -> str:
        return (
            f"<PropertyPhoto id={self.id} property_id={self.property_id} "
            f"primary={self.is_primary} order={self.sort_order}>"
        )
