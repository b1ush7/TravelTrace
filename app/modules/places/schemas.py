from datetime import datetime

from pydantic import BaseModel


class PlaceOut(BaseModel):
    id: str
    name: str
    city: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    coordinate_system: str | None = None
    source: str
    opening_hours: str | None = None
    price_cny: float | None = None
    verified_at: datetime | None = None


class KnowledgeHitOut(BaseModel):
    title: str
    excerpt: str
    source_url: str
    verified_at: datetime | None = None
