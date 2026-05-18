import uuid

from pydantic import BaseModel, ConfigDict


class PropertyTypeOut(BaseModel):
    value: str
    label: str
    icon_key: str


class PrivacyTypeOut(BaseModel):
    value: str
    label: str
    description: str
    icon_key: str


class FieldConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    entity: str
    field_name: str
    visible: bool
    required: bool


class FieldConfigUpdate(BaseModel):
    visible: bool | None = None
    required: bool | None = None
