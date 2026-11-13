from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProposalOptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=200)


class CreateProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conflict_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    options: list[ProposalOptionIn] = Field(min_length=2, max_length=10)
    expected_room_version: int = Field(ge=1)
    deadline: datetime | None = None


class VoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: UUID
    expected_proposal_version: int = Field(ge=1)


class VoteResult(BaseModel):
    proposal_id: UUID
    option_id: UUID
    member_id: UUID


class ConcludeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_room_version: int = Field(ge=1)
    expected_proposal_version: int = Field(ge=1)


class ProposalOut(BaseModel):
    id: UUID
    conflict_id: UUID | None = None
    title: str
    options: list[dict]
    status: Literal["open", "decided", "closed_no_consensus", "stale"]
    created_at: datetime
    votes: list[dict]
    pending_member_ids: list[UUID]
    affected_hard_constraint_member_ids: list[UUID]
    deadline: datetime | None = None
    version: int
    eligible_member_ids: list[UUID]
    decision_id: UUID | None = None
    outcome_rule: Literal["absolute_majority"] = "absolute_majority"


class DecisionOut(BaseModel):
    id: UUID
    proposal_id: UUID
    selected_option_id: UUID
    room_version: int
    effect: Literal["preference_recorded", "requires_personal_confirmation"]
    pending_member_ids: list[UUID]
    created_at: datetime
