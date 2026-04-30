"""Product request/response DTOs.

Keeps the domain entity off the HTTP surface so server-managed fields (id,
timestamps) can't be set by clients and so request/response shapes can evolve
independently of the persistence model.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProductCreate(BaseModel):
    """Inbound payload for ``POST``. Server-managed fields are excluded."""


class ProductRead(BaseModel):
    """Outbound representation including server-managed fields."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class ProductUpdate(BaseModel):
    """Partial-update payload — every field is optional.

    The service applies ``model_dump(exclude_unset=True)`` so only fields
    explicitly supplied by the client are touched.
    """
