import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SubscriptionPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    # null on the wire == unlimited.
    monthly_bid_limit: int | None
    monthly_property_limit: int | None
    broker_phone_visible: bool
    price: Decimal
    is_active: bool


class UserSubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    plan: SubscriptionPlanOut
    starts_at: datetime
    expires_at: datetime | None


class AssignPlanIn(BaseModel):
    plan_code: Literal["free", "pro", "pro_max", "unlimited"]


class PlanUpdateIn(BaseModel):
    """Admin can adjust any of these limits. All fields optional —
    only the fields explicitly sent get patched."""

    name: str | None = None
    monthly_bid_limit: int | None = None
    monthly_property_limit: int | None = None
    broker_phone_visible: bool | None = None
    price: Decimal | None = None
    is_active: bool | None = None


# Useful summary the bid endpoints can return on 429 so the UI can prompt
# an upgrade with concrete numbers.
class QuotaSummary(BaseModel):
    plan_code: str
    monthly_bid_limit: int | None
    used_this_month: int
    remaining: int | None


class MySubscriptionOut(BaseModel):
    """Shown in the profile page for both agent and manager roles."""

    plan_code: str
    plan_name: str
    price: Decimal
    monthly_bid_limit: int | None
    monthly_property_limit: int | None
    broker_phone_visible: bool
    bids_used_this_month: int
    bids_remaining: int | None
    properties_used: int
    properties_remaining: int | None
    # Which counter the "bids_used" refers to — depends on active_role.
    quota_basis: Literal["bids_placed", "bids_accepted"]
