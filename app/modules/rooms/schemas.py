from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InterestSummary(BaseModel):
    common_count: int = 0
    conflict_count: int = 0


class CreateRoom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    destination: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    theme_code: str | None = Field(default=None, max_length=64)
    interest_tag_codes: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("name", "destination")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()

    @field_validator("interest_tag_codes")
    @classmethod
    def unique_tags(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("兴趣标签不能重复")
        return value

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        return self


class RoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    destination: str
    start_date: date
    end_date: date
    owner_id: UUID
    version: int
    status: str
    created_at: datetime
    confirmation_rule: Literal["all_active_members"] = "all_active_members"
    theme_code: str | None = None
    interest_summary: InterestSummary = Field(default_factory=InterestSummary)


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    room_id: UUID
    user_id: UUID
    display_name: str
    role: Literal["owner", "member"]
    status: Literal["active", "left"]
    joined_at: datetime


class CreateInvitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_in_hours: int = Field(default=24, ge=1, le=168)


class InvitationResponse(BaseModel):
    invite_code: str
    expires_at: datetime


class JoinRoom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invite_code: str = Field(min_length=8, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("display_name")
    @classmethod
    def clean(cls, value):
        if value is not None and not value.strip():
            raise ValueError("显示名不能为空")
        return value.strip() if value else value

class TravelWindowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starts_at: datetime
    ends_at: datetime
    time_zone: str = Field(min_length=1, max_length=64)
    expected_room_version: int = Field(ge=1)


class TravelWindowOut(BaseModel):
    starts_at: datetime
    ends_at: datetime
    time_zone: str
    room_version: int

class RevokedCount(BaseModel):
    revoked_count: int


class LeftRoom(BaseModel):
    left: bool
