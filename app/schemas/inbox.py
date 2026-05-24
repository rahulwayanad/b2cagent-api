import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event: str
    title: str
    body: str
    link: str | None
    related_bid_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime


class UnreadCountOut(BaseModel):
    notifications: int
    messages: int


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    bid_id: uuid.UUID
    sender_id: uuid.UUID
    sender_name: str
    body: str
    read_at: datetime | None
    created_at: datetime


class MessageCreateIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


class ThreadOut(BaseModel):
    """A bid-scoped chat thread surfaced in the inbox list."""

    model_config = ConfigDict(from_attributes=True)
    bid_id: uuid.UUID
    property_id: uuid.UUID
    property_name: str
    other_party_id: uuid.UUID
    other_party_name: str
    last_message: str | None
    last_message_at: datetime | None
    unread_count: int
    bid_status: str
    bid_check_in: str
    bid_check_out: str
