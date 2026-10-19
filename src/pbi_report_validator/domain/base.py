"""Base class shared by all domain models."""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Base class: frozen, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")
