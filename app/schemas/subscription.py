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


# Useful summary the bid endpoints can return on 429 so the UI can prompt
# an upgrade with concrete numbers.
class QuotaSummary(BaseModel):
    plan_code: str
    monthly_bid_limit: int | None
    used_this_month: int
    remaining: int | None
