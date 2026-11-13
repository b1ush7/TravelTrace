from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateDeal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    place_name: str | None = Field(default=None, max_length=120)
    price_cny: float | None = Field(default=None, ge=0)
    people_count: int | None = Field(default=None, ge=1)
    valid_until: datetime | None = None
    url: str | None = Field(default=None, max_length=500)


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    place_name: str | None = None
    price_cny: float | None = None
    people_count: int | None = None
    valid_until: datetime | None = None
    url: str | None = None
    source: Literal["user", "authorized_provider"]
    verification_status: Literal["unverified", "confirmed", "expired"]
    confirmed_by: list[UUID] = Field(default_factory=list)
