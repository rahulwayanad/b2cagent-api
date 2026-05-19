from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import LeadStatus
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.bid import Bid
    from app.models.property import Property
    from app.models.user import User


class Lead(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "leads"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Where the customer wants to stay (from OpenStreetMap/Nominatim).
    customer_location_text: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    customer_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    customer_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    check_out: Mapped[date] = mapped_column(Date, nullable=False)
    is_single_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    adults: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    budget_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    special_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[LeadStatus] = mapped_column(
        SAEnum(LeadStatus, name="lead_status"),
        nullable=False,
        default=LeadStatus.draft,
    )

    agent: Mapped["User"] = relationship("User")
    matches: Mapped[list["LeadPropertyMatch"]] = relationship(
        "LeadPropertyMatch",
        back_populates="lead",
        cascade="all, delete-orphan",
    )
    bids: Mapped[list["Bid"]] = relationship(
        "Bid",
        back_populates="lead",
        cascade="all, delete-orphan",
    )


class LeadPropertyMatch(UUIDPKMixin, Base):
    __tablename__ = "lead_property_matches"
    __table_args__ = (
        UniqueConstraint("lead_id", "property_id", name="uq_lead_property_match"),
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
    match_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    lead: Mapped["Lead"] = relationship("Lead", back_populates="matches")
    property: Mapped["Property"] = relationship("Property")
