from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConflictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    type: Literal["budget", "time", "place", "other"]
    description: str
    claim_ids: list[UUID] = Field(default_factory=list)
    affected_member_ids: list[UUID] = Field(default_factory=list)
    status: Literal["open", "resolved"]
    severity: Literal["low", "medium", "high"]
    key_member_ids: list[UUID] = Field(default_factory=list)
    resolution_count: int


class ResolutionCost(BaseModel):
    time_delta_minutes: int | None = None
    cost_delta_cny: float | None = None
    walking_delta_m: int | None = None


class ResolutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conflict_id: UUID
    action: Literal["relax", "replace", "shift", "split", "rotate", "vote", "leave", "defer"]
    title: str
    description: str
    affected_member_ids: list[UUID]
    required_member_ids: list[UUID]
    cost: ResolutionCost
    feasibility: Literal["feasible", "needs_data", "infeasible"]
    rank: int


class ResolutionsOut(BaseModel):
    conflict_id: UUID
    room_version: int
    options: list[ResolutionOut]


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: UUID
    expected_room_version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=500)


class ResolveResult(BaseModel):
    effect: Literal["applied", "pending_confirmation"]
    room_version: int
    version_id: UUID | None = None
    proposal_id: UUID | None = None
    pending_member_ids: list[UUID] = Field(default_factory=list)


class PlanIssueOut(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning", "unknown"]
    member_ids: list[UUID]
    activity_ids: list[UUID]
    adjustment_options: list[str]


class ConflictRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_room_version: int = Field(ge=1)
    include_theme_rules: bool = True
    include_interest_clash: bool = True


class ConflictRefreshOut(BaseModel):
    room_version: int
    conflicts: list[ConflictOut]
    issues: list[PlanIssueOut] = Field(default_factory=list)
