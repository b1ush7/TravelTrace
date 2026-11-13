from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NextMeeting(BaseModel):
    title: str
    place_name: str
    at: datetime


class TravelCard(BaseModel):
    room_id: UUID
    room_name: str
    destination: str
    theme_code: str | None = None
    days_to_start: int | None = None
    start_date: date
    end_date: date
    pending_confirmations: int
    next_meeting: NextMeeting | None = None
    current_version_id: UUID | None = None
    deep_link: str
    updated_at: datetime


class LiveAction(BaseModel):
    action: Literal["open", "confirm", "navigate", "ack"]
    label: str
    deep_link: str


class LivePrivacy(BaseModel):
    hide_members: bool = True
    hide_budget: bool = True


class LiveState(BaseModel):
    room_id: UUID
    version_id: UUID
    stage: Literal["before", "traveling", "activity", "meeting", "split", "ended"]
    title: str
    subtitle: str
    countdown_to: datetime | None = None
    progress: float | None = Field(default=None, ge=0, le=1)
    actions: list[LiveAction]
    privacy: LivePrivacy
    updated_at: datetime
    expires_at: datetime


class PushSubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=1, max_length=128)
    platform: Literal["coloros", "android", "ios", "web"]
    capabilities: list[Literal["fluid_cloud", "card", "push"]]
    app_version: str = Field(min_length=1, max_length=32)
    push_token: str = Field(min_length=1, max_length=4096)


class PushSubscriptionOut(BaseModel):
    id: UUID
    device_id: str
    platform: Literal["coloros", "android", "ios", "web"]
    capabilities: list[str]
    app_version: str
    push_token_masked: str | None = None
    created_at: datetime
    last_seen_at: datetime


class PlanNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version_id: UUID
    kind: Literal["change_published", "reminder_updated", "confirmation_needed", "meeting_soon", "activity_starting"]
    delivery_status: Literal["pending", "sent", "delivered", "failed"]
    created_at: datetime
    superseded: bool
    channel: Literal["fluid_cloud", "card", "push", "in_app"]
    acked_at: datetime | None = None
    deep_link: str | None = None


class AckResult(BaseModel):
    notification_id: UUID
    acked_at: datetime
