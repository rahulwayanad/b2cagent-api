from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.user import User


class SubscriptionPlan(UUIDPKMixin, TimestampMixin, Base):
    """Bid-quota tier. Seeded with: free / pro / pro_max / unlimited."""

    __tablename__ = "subscription_plans"

    code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL == unlimited.
    monthly_bid_limit: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # NULL == unlimited properties.
    monthly_property_limit: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # When false, agent/manager contact phone is hidden across the app.
    broker_phone_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    subscriptions: Mapped[list["UserSubscription"]] = relationship(
        "UserSubscription", back_populates="plan"
    )


class UserSubscription(UUIDPKMixin, TimestampMixin, Base):
    """One active plan assignment per user. Admin can swap by upserting on
    user_id. Absence of a row means the user is implicitly on the free tier."""

    __tablename__ = "user_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_subscriptions_user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # NULL == no fixed expiry (e.g. free plan).
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    plan: Mapped["SubscriptionPlan"] = relationship(
        "SubscriptionPlan", back_populates="subscriptions"
    )
    user: Mapped["User"] = relationship("User")
