from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    ForeignKey,
    Numeric,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.property import Property


class PropertyDayPrice(UUIDPKMixin, TimestampMixin, Base):
    """Per-night rate override for a single date on a property.

    NULL on either rate means "inherit the property's base rate" for that
    component — the manager can override just the floor, just the asking
    rate, or both.
    """

    __tablename__ = "property_day_prices"
    __table_args__ = (
        UniqueConstraint(
            "property_id", "date", name="uq_day_prices_property_date"
        ),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    b2b_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    b2c_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    property: Mapped["Property"] = relationship(
        "Property", back_populates="day_prices"
    )

    def __repr__(self) -> str:
        return (
            f"<PropertyDayPrice property_id={self.property_id} "
            f"date={self.date} b2b={self.b2b_rate} b2c={self.b2c_rate}>"
        )
