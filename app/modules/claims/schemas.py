from datetime import date as date_type, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


Polarity = Literal["positive", "negative", "unknown"]
Strength = Literal["hard", "soft", "unknown"]
ClaimStatus = Literal["pending", "confirmed", "rejected", "withdrawn"]


class ClaimValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = None
    amount_cny: float | None = Field(default=None, ge=0)
    scope: Literal["per_person", "total", "unspecified"] | None = None
    includes_accommodation: bool | None = None
    date: date_type | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    place_id: str | None = None
    place_name: str | None = None
    max_walking_km: float | None = Field(default=None, ge=0)


class CreateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1, max_length=32)
    value: ClaimValue
    condition: str | None = Field(default=None, max_length=500)
    polarity: Polarity = "unknown"
    strength: Strength


class UpdateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: ClaimValue | None = None
    condition: str | None = Field(default=None, max_length=500)
    polarity: Polarity | None = None
    strength: Strength | None = None
    expected_version: int = Field(ge=1)


class ClaimDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["confirm", "reject", "withdraw"]
    expected_version: int = Field(ge=1)


class ClaimOut(BaseModel):
    id: UUID
    subject_member_id: UUID | None = None
    speaker_member_id: UUID | None = None
    field: str
    value: ClaimValue
    condition: str | None = None
    polarity: Polarity = "unknown"
    strength: Strength = "unknown"
    status: ClaimStatus
    source_message_id: UUID | None = None
    version: int


class ParticipationOut(BaseModel):
    member_id: UUID
    joins_at: datetime
    leaves_at: datetime
    allow_solo: bool
    room_version: int


class ParticipationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    joins_at: datetime
    leaves_at: datetime
    allow_solo: bool
    expected_room_version: int = Field(ge=1)