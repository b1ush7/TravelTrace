from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.claims.schemas import ClaimOut, ParticipationOut
from app.modules.interests.schemas import RoomInterestOverviewOut
from app.modules.reach.schemas import LiveState, NextMeeting
from app.modules.rooms.schemas import RoomResponse


class PlanActivityOut(BaseModel):
    id: UUID
    activity_id: UUID | None = None
    title: str
    place_name: str
    map_place_id: str | None = None
    starts_at: datetime
    ends_at: datetime
    member_ids: list[UUID]
    branch_id: UUID | None = None
    kind: Literal["activity", "meeting"]
    commitment: Literal["flexible", "fixed"]
    execution_state: Literal["planned", "in_progress", "completed", "skipped"]
    estimated_cost_cny: float | None = None
    source_note: str | None = None


class PlanConnectionOut(BaseModel):
    from_id: UUID
    to_id: UUID
    member_ids: list[UUID]
    kind: Literal["travel", "synchronization"]
    travel_minutes: int | None = None
    source: str | None = None


class SplitSegmentOut(BaseModel):
    groups: list[dict]
    meeting_activity_id: UUID
    meeting_window_start: datetime
    meeting_window_end: datetime
    together_ratio: float | None = None


class PlanImpactOut(BaseModel):
    changed_activity_ids: list[UUID] = Field(default_factory=list)
    affected_member_ids: list[UUID] = Field(default_factory=list)
    required_member_ids: list[UUID] = Field(default_factory=list)
    changed_commitment_ids: list[UUID] = Field(default_factory=list)
    cost_delta_cny: float | None = None
    time_delta_minutes: int | None = None
    unknowns: list[str] = Field(default_factory=list)


class PlanApprovalOut(BaseModel):
    member_id: UUID
    decision: Literal["pending", "approve", "reject", "request_changes"]
    decided_at: datetime | None = None
    comment: str = ""


class PlanVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    room_id: UUID
    proposer_member_id: UUID
    base_version_id: UUID | None
    input_room_version: int
    status: Literal["draft", "validating", "awaiting_confirmation", "published",
                    "infeasible", "rejected", "expired", "cancelled", "superseded"]
    expires_at: datetime | None = None
    published_at: datetime | None = None
    activities: list[PlanActivityOut] = Field(default_factory=list)
    connections: list[PlanConnectionOut] = Field(default_factory=list)
    split_segments: list[SplitSegmentOut] = Field(default_factory=list)
    participation: list[ParticipationOut] = Field(default_factory=list)
    estimated_cost_cny: float | None = None
    member_budgets: list[dict] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    impact: PlanImpactOut = Field(default_factory=PlanImpactOut)
    approvals: list[PlanApprovalOut] = Field(default_factory=list)
    theme_code: str | None = None
    card_summary: dict | None = None


class ActivityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    place_name: str = Field(min_length=1, max_length=120)
    place_id: str | None = Field(default=None, max_length=64)
    duration_minutes: int = Field(ge=0, le=1440)
    estimated_cost_cny: float | None = Field(ge=0)
    cost_scope: Literal["per_person", "total"]
    window_start: datetime | None = None
    window_end: datetime | None = None
    reserved_start: datetime | None = None
    reservation_status: Literal["none", "unconfirmed", "confirmed"] = "none"
    source_note: str | None = Field(default=None, max_length=500)
    expected_room_version: int = Field(ge=1)


class ActivityOut(BaseModel):
    id: UUID
    owner_member_id: UUID
    name: str
    place_name: str
    place_id: str | None = None
    duration_minutes: int
    estimated_cost_cny: float | None = None
    cost_scope: Literal["per_person", "total"]
    window_start: datetime | None = None
    window_end: datetime | None = None
    reserved_start: datetime | None = None
    reservation_status: Literal["none", "unconfirmed", "confirmed"]
    source_type: Literal["manual", "authorized_api", "demo"] = "manual"
    source_note: str | None = None
    observed_at: datetime
    room_version: int


class InitialPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_room_version: int = Field(ge=1)
    activity_ids: list[UUID] = Field(min_length=1, max_length=12)
    allow_split: bool = False
    theme_code: str | None = None
    interest_weight: float = Field(default=0.5, ge=0, le=1)
    must_tag_codes: list[str] = Field(default_factory=list)
    avoid_tag_codes: list[str] = Field(default_factory=list)


class PlanningJobOut(BaseModel):
    id: UUID
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "timed_out"]
    outcome: Literal["feasible", "infeasible", "data_missing", "unknown"] | None = None
    stage: Literal["validating", "solving", "calculating_impact", "finished"]
    result_version_id: UUID | None = None
    issues: list[dict] = Field(default_factory=list)


class PlanValidationOut(BaseModel):
    version_id: UUID
    outcome: Literal["feasible", "infeasible", "data_missing", "unknown"]
    issues: list[dict]


class PlanDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_room_version: int = Field(ge=1)
    expected_current_version_id: UUID | None
    decision: Literal["approve", "reject", "request_changes"]
    comment: str | None = Field(default=None, max_length=500)


class PlanRevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_room_version: int = Field(ge=1)
    expected_current_version_id: UUID | None


class NextStepOut(BaseModel):
    current_version_id: UUID
    next_activity: PlanActivityOut | None = None
    departure_at: datetime | None = None
    meeting_activity: PlanActivityOut | None = None
    navigation_url: str | None = None
    synced_at: datetime
    live: LiveState | None = None
    theme: dict | None = None
    deep_link: str | None = None


class ConflictSummary(BaseModel):
    open: int
    resolved: int
    key_member_ids: list[UUID] = Field(default_factory=list)


class RoomOverviewV06Out(BaseModel):
    room: RoomResponse
    schedule: dict
    participation: list[ParticipationOut]
    claims: list[ClaimOut]
    conflicts: list[dict]
    current_version_id: UUID | None
    pending_plans: list[PlanVersionOut]
    theme_code: str | None = None
    interests: RoomInterestOverviewOut | None = None
    conflict_summary: ConflictSummary
    live: LiveState | None = None
    next_meeting: NextMeeting | None = None

class LocalChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version_id: UUID
    expected_room_version: int = Field(ge=1)
    operation: Literal["replace", "skip", "resize", "leave_early", "restore"]
    target_activity_id: UUID | None = None
    replacement_activity_id: UUID | None = None
    duration_minutes: int | None = Field(default=None, ge=1)
    leaves_at: datetime | None = None
    restore_version_id: UUID | None = None


class ExecutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_current_version_id: UUID
    expected_room_version: int = Field(ge=1)
    state: Literal["in_progress", "completed"]


class ExecutionOut(BaseModel):
    activity_id: UUID
    member_id: UUID
    current_version_id: UUID
    room_version: int
    state: Literal["in_progress", "completed"]
    updated_at: datetime