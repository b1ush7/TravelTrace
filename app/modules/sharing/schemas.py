from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ShareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_at: datetime


class ShareLinkOut(BaseModel):
    id: UUID
    url: str
    expires_at: datetime


class SharedActivity(BaseModel):
    title: str
    place_name: str
    starts_at: datetime
    ends_at: datetime
    kind: Literal["activity", "meeting"]


class SharedTheme(BaseModel):
    code: str
    name: str
    badge: str


class CreateRoomHint(BaseModel):
    destination: str
    theme_code: str | None = None
    days: int


class SharedPlanOut(BaseModel):
    destination: str
    updated_at: datetime
    activities: list[SharedActivity]
    theme: SharedTheme | None = None
    create_room_hint: CreateRoomHint | None = None
