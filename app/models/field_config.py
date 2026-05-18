from __future__ import annotations

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class FieldConfig(UUIDPKMixin, TimestampMixin, Base):
    """Super-admin-controlled visibility for entity fields.

    A row like (entity='property', field_name='lat', visible=False) means the
    UI hides the lat input and the backend rejects requests that try to set it.
    """

    __tablename__ = "field_configs"
    __table_args__ = (
        UniqueConstraint(
            "entity", "field_name", name="uq_field_configs_entity_field"
        ),
    )

    entity: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    def __repr__(self) -> str:
        return (
            f"<FieldConfig {self.entity}.{self.field_name} "
            f"visible={self.visible} required={self.required}>"
        )
