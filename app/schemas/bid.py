import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models import BidStatus


# Manager-facing — includes the bidder's identity. Agents bid via /leads.
class BidWithAgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    property_id: uuid.UUID
    check_in: date
    check_out: date
    amount: Decimal
    status: BidStatus
    agent_id: uuid.UUID
    agent_name: str
    agent_email: str
    created_at: datetime
