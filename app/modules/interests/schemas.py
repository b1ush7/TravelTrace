from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


Domain = Literal["nature", "culture", "food", "play", "shopping", "nightlife", "red", "outdoor", "photo", "show", "family"]
Role = Literal["must", "want", "avoid"]
Visibility = Literal["public", "room", "private"]
Source = Literal["self", "ai", "history"]


class InterestTagOut(BaseModel):
    code: str
    name: str
    domain: Domain
    parent_code: str | None = None
    icon: str | None = None
    sort: int


class MemberInterestOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag_code: str = Field(min_length=1, max_length=64)
    strength: int = Field(ge=1, le=5)
    role: Role
    visibility: Visibility
    source: Source


class InterestsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    interests: list[MemberInterestOut] = Field(max_length=30)


class MemberInterestProfileOut(BaseModel):
    member_id: UUID
    interests: list[MemberInterestOut]
    version: int
    updated_at: datetime


class DomainShare(BaseModel):
    domain: str
    count: int
    share: float


class TopTag(BaseModel):
    tag_code: str
    name: str
    count: int


class DriftItem(BaseModel):
    tag_code: str
    delta: int


class InterestStatsOut(BaseModel):
    total_tags: int
    by_domain: list[DomainShare]
    top_tags: list[TopTag]
    drift: list[DriftItem]


class ClashTag(BaseModel):
    tag_code: str
    name: str
    must_member_ids: list[UUID]
    avoid_member_ids: list[UUID]


class RoomInterestOverviewOut(BaseModel):
    room_id: UUID
    member_count: int
    filled_member_count: int
    common_tags: list[InterestTagOut]
    clash_tags: list[ClashTag]
    coverage: float
    private_excluded: int
