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


# Agent-facing — one of their own bids with property + lead context.
class AgentBidOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    lead_id: uuid.UUID
    property_id: uuid.UUID
    property_name: str
    property_location: str | None
    customer_name: str
    customer_phone: str | None
    check_in: date
    check_out: date
    adults: int
    children: int
    amount: Decimal
    status: BidStatus
    created_at: datetime


# Manager-facing — one bid across any of their properties, with agent + lead.
class ManagerBidOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    lead_id: uuid.UUID
    property_id: uuid.UUID
    property_name: str
    property_location: str | None
    agent_id: uuid.UUID
    agent_name: str
    agent_email: str
    customer_name: str
    check_in: date
    check_out: date
    adults: int
    children: int
    amount: Decimal
    status: BidStatus
    created_at: datetime
