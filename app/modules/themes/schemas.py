from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ThemeOut(BaseModel):
    code: str
    name: str
    summary: str
    cover_url: str | None = None
    domains: list[str]
    city_scope: str
    fact_count: int
    pack_count: int
    is_demo: bool
    status: Literal["draft", "active", "archived"]
    updated_at: datetime


class ThemeRuleOut(BaseModel):
    code: str
    description: str
    severity: Literal["error", "warning", "info"]
    applies_to: Literal["activity", "transport", "meeting"]


class ThemeFactOut(BaseModel):
    id: str
    category: Literal["opening", "ticket", "reservation", "docent", "etiquette", "transport"]
    title: str
    place_name: str
    place_id: str | None = None
    value: str
    source: str
    observed_at: datetime
    verified: bool
    stale: bool


class ThemePackItemOut(BaseModel):
    place_name: str
    place_id: str | None = None
    duration_minutes: int
    estimated_cost_cny: float
    window_start: str | None = None
    window_end: str | None = None


class ThemePackOut(BaseModel):
    id: str
    theme_code: str
    name: str
    days: int = Field(ge=1, le=7)
    city: str
    items: list[ThemePackItemOut]
    suitable_group: str | None = None
    notes: str | None = None


class ThemeDetailOut(BaseModel):
    theme: ThemeOut
    rules: list[ThemeRuleOut]
    facts: list[ThemeFactOut]


class SetRoomTheme(BaseModel):
    theme_code: str | None
    expected_room_version: int = Field(ge=1)