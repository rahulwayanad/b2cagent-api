from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.bid import Bid
    from app.models.lead import Lead
    from app.models.property import Property
    from app.models.user import User


class BookingStatus(str, enum.Enum):
    active = "active"
    cancelled = "cancelled"


class Booking(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "bookings"

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    bid_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("bids.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    check_out: Mapped[date] = mapped_column(Date, nullable=False)
    guests: Mapped[int] = mapped_column(nullable=False, default=1)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus, name="booking_status"),
        nullable=False,
        default=BookingStatus.active,
    )

    property: Mapped["Property"] = relationship("Property")
    lead: Mapped["Lead | None"] = relationship("Lead")
    bid: Mapped["Bid | None"] = relationship("Bid")
    agent: Mapped["User | None"] = relationship("User")


class PropertyAvailabilityBlock(UUIDPKMixin, TimestampMixin, Base):
    """Manager-created date range marking the property as unavailable."""

    __tablename__ = "property_availability_blocks"

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    property: Mapped["Property"] = relationship("Property")
