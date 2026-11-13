from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=20000)
    consent_confirmed: Literal[True]
    retention: Literal["discard_after_extraction", "retain_until_deleted"]


class ChatImportResult(BaseModel):
    import_id: UUID
    job_id: UUID
    retention: Literal["discard_after_extraction", "retain_until_deleted"]
    raw_status: Literal["pending", "retained", "deleted"]


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_room_version: int = Field(ge=1)
    message_ids: list[UUID] | None = None


class JobOut(BaseModel):
    id: UUID
    room_id: UUID
    kind: Literal["extract", "plan", "replan"]
    status: Literal["queued", "running", "awaiting_confirmation", "succeeded", "failed", "timed_out"]
    result_version_id: UUID | None = None
    error: dict | None = None
    created_at: datetime
    result_version_ids: list[UUID] = Field(default_factory=list)
    planning_outcome: Literal["feasible", "infeasible", "unknown", "data_missing"] | None = None
    input_room_version: int | None = None
    stage: Literal["extracting", "waiting_members", "retrieving", "optimizing", "validating", "finished"]
    progress_message: str | None = None

class DeletedResult(BaseModel):
    deleted: bool
