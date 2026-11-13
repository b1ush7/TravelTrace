from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ArchiveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_room_version: int = Field(ge=1)


class PlannedVsActual(BaseModel):
    on_time_rate: float
    changed_activities: int
    skipped_activities: int


class RetroCost(BaseModel):
    estimated_cny: float
    actual_cny: float
    per_person_cny: float


class Concession(BaseModel):
    member_id: UUID
    count: int


class RetrospectiveOut(BaseModel):
    room_id: UUID
    version_id: UUID
    planned_vs_actual: PlannedVsActual
    cost: RetroCost
    conflicts_resolved: int
    concessions: list[Concession]
    highlights: list[str]
    generated_at: datetime


class RoomTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    source_room_id: UUID
    destination: str
    theme_code: str | None = None
    days: int
    member_count: int
    interest_tag_codes: list[str]
    items: list[dict] | None = None
    created_at: datetime
    last_used_at: datetime | None = None


class FromTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: UUID
    name: str = Field(min_length=1, max_length=80)
    start_date: date
    end_date: date
