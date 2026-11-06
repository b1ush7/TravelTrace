from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("消息不能为空")
        return value


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence: int
    author_member_id: UUID
    content: str
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageResponse]
    next_cursor: int = Field(description="将此值作为下一次 after 参数；仅随已返回消息前进")
    has_more: bool
