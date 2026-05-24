import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EmailTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    subject: str
    body: str
    description: str | None
    is_active: bool
    updated_at: datetime


class EmailTemplateUpdateIn(BaseModel):
    """All fields optional — admin can patch a subset."""

    name: str | None = Field(None, min_length=1, max_length=120)
    subject: str | None = Field(None, min_length=1, max_length=255)
    body: str | None = Field(None, min_length=1)
    description: str | None = None
    is_active: bool | None = None
