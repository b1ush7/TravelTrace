from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CreateRoom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    destination: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date

    @field_validator("name", "destination")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()

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
