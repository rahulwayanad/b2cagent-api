from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import BidStatus
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.bid_payment import BidPayment
    from app.models.lead import Lead
    from app.models.property import Property
    from app.models.user import User


class Bid(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "bids"
    __table_args__ = (
        UniqueConstraint("lead_id", "property_id", name="uq_bids_lead_property"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    check_out: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BidStatus] = mapped_column(
        SAEnum(BidStatus, name="bid_status"),
        nullable=False,
        default=BidStatus.pending,
    )
    # Set the moment a manager accepts this bid. Drives the manager's
    # monthly accept-quota count, independent of later status changes.
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    lead: Mapped["Lead"] = relationship("Lead", back_populates="bids")
    property: Mapped["Property"] = relationship("Property", back_populates="bids")
    agent: Mapped["User"] = relationship("User", back_populates="bids")
    payment: Mapped["BidPayment | None"] = relationship(
        "BidPayment", back_populates="bid", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Bid id={self.id} lead_id={self.lead_id} property_id={self.property_id} "
            f"check_in={self.check_in} amount={self.amount} status={self.status.value}>"
        )
