from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import PaymentMethod, PaymentStatus
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.bid import Bid


class BidPayment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "bid_payments"
    __table_args__ = (
        UniqueConstraint("bid_id", name="uq_bid_payments_bid_id"),
    )

    bid_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("bids.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    method: Mapped[PaymentMethod] = mapped_column(
        SAEnum(PaymentMethod, name="payment_method"),
        nullable=False,
    )
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, name="payment_status"),
        nullable=False,
        default=PaymentStatus.initiated,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    bid: Mapped["Bid"] = relationship("Bid", back_populates="payment")
