"""Normalize database rows into the plain data the solver works on.

The planner used to read `ActivityFact` only and ignore confirmed claims and
participation windows entirely. Everything the solver may branch on is
assembled here, and nothing in this module queries or writes on its own behalf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ActivityFact, Claim, Member, Participation, Room
from app.modules.places import catalog as places

# Planning never schedules outside this band; the design keeps a day's walk
# inside daylight hours and treats anything later as a new day.
DAY_START = time(9, 0)
DAY_END = time(19, 0)
MIN_ACTIVITY_MINUTES = 15


def _dt(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def place_key(*candidates: str | None) -> str | None:
    """Collapse id/name/text into one comparable key for avoid matches."""
    for item in candidates:
        if item and str(item).strip():
            return str(item).strip().lower()
    return None


@dataclass(frozen=True)
class MemberWindow:
    member_id: UUID
    start: datetime
    end: datetime
    allow_solo: bool = False
    budget_cny: float | None = None
    budget_scope: str | None = None
    budget_claim_id: UUID | None = None
    avoid_keys: frozenset[str] = frozenset()
    max_walking_km: float | None = None
    participation_id: UUID | None = None
    has_participation: bool = False

    def covers(self, start: datetime, end: datetime) -> bool:
        return self.start <= start and end <= self.end

    def overlap(self, start: datetime, end: datetime) -> bool:
        return start < self.end and self.start < end


@dataclass(frozen=True)
class ActivitySlot:
    activity_id: UUID
    name: str
    place_name: str
    place_id: str | None
    duration_minutes: int
    earliest: datetime
    latest_end: datetime
    fixed_start: datetime | None
    cost_cny: float
    cost_scope: str
    open_windows: tuple[tuple[time, time], ...] = ()
    closed_weekdays: frozenset[int] = frozenset()
    all_day: bool = False
    latitude: float | None = None
    longitude: float | None = None
    owner_member_id: UUID | None = None
    source_note: str | None = None
    reservation_status: str = "none"
    opening_known: bool = False
    travel_known: bool = False

    @property
    def resolved_place_key(self) -> str:
        return place_key(self.place_id, self.place_name) or ""


@dataclass
class PlanContext:
    room_id: UUID
    start_date: date
    end_date: date
    tz: ZoneInfo
    members: list[MemberWindow] = field(default_factory=list)
    slots: list[ActivitySlot] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    data_missing: bool = False

    @property
    def active_member_ids(self) -> list[UUID]:
        return [item.member_id for item in self.members]

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    def day_bounds(self, day_index: int) -> tuple[datetime, datetime]:
        current = self.start_date + timedelta(days=day_index)
        return (datetime.combine(current, DAY_START, tzinfo=self.tz),
                datetime.combine(current, DAY_END, tzinfo=self.tz))


def _room_window(room: Room, tz) -> tuple[datetime, datetime]:
    start = _dt(room.window_starts_at) or datetime.combine(room.start_date, time(0, 0), tzinfo=tz)
    end = _dt(room.window_ends_at) or datetime.combine(room.end_date, time(23, 59, 59), tzinfo=tz)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    return start.astimezone(tz), end.astimezone(tz)


def _budget_of(claim: Claim, member_count: int) -> tuple[float | None, str | None]:
    value = claim.value or {}
    amount = value.get("amount_cny")
    if amount is None:
        return None, None
    scope = value.get("scope") or "unspecified"
    amount = float(amount)
    if scope == "total" and member_count > 0:
        return amount / member_count, "total"
    return amount, scope


def build_context(session: Session, room: Room, facts: list[ActivityFact]) -> PlanContext:
    """Assemble solver input from facts, confirmed hard claims and participation."""
    tz = ZoneInfo(room.time_zone or "Asia/Shanghai")
    context = PlanContext(room_id=room.id, start_date=room.start_date, end_date=room.end_date, tz=tz)

    active = list(session.scalars(select(Member).where(
        Member.room_id == room.id, Member.status == "active")).all())
    member_count = max(len(active), 1)
    participations = {row.member_id: row for row in session.scalars(
        select(Participation).where(Participation.room_id == room.id)).all()}

    claims = list(session.scalars(select(Claim).where(
        Claim.room_id == room.id, Claim.status == "confirmed", Claim.strength == "hard")).all())

    windows: dict[UUID, list[tuple[datetime, datetime]]] = {}
    budgets: dict[UUID, tuple[float | None, str | None, Claim]] = {}
    avoids: dict[UUID, set[str]] = {}
    walking: dict[UUID, float] = {}
    for claim in claims:
        if claim.subject_member_id is None:
            continue
        value = claim.value or {}
        if claim.field in {"time", "schedule"}:
            start = _dt(value.get("start_time")) or _dt(value.get("date"))
            end = _dt(value.get("end_time"))
            if start and end and start < end:
                windows.setdefault(claim.subject_member_id, []).append((start, end))
            elif start or end:
                context.unknowns.append("时间条件缺少开始或结束，已忽略")
        elif claim.field == "budget":
            amount, scope = _budget_of(claim, member_count)
            if amount is not None:
                budgets[claim.subject_member_id] = (amount, scope, claim)
        elif claim.field in {"place", "preference", "interest"} and claim.polarity == "negative":
            key = place_key(value.get("place_id"), value.get("place_name"), value.get("text"))
            if key:
                avoids.setdefault(claim.subject_member_id, set()).add(key)
        elif claim.field == "walking":
            limit = value.get("max_walking_km")
            if limit is not None:
                walking[claim.subject_member_id] = float(limit)

    room_start, room_end = _room_window(room, tz)
    for member in active:
        row = participations.get(member.id)
        if row is None:
            context.data_missing = True
            # Reported once per room, not once per member.
            if "参与区间未填写" not in context.unknowns:
                context.unknowns.append("参与区间未填写")
            start, end = room_start, room_end
            has_participation = False
            participation_id = None
        else:
            start = _dt(row.joins_at) or room_start
            end = _dt(row.leaves_at) or room_end
            start, end = start.astimezone(tz), end.astimezone(tz)
            has_participation = True
            participation_id = row.id
        for claim_start, claim_end in windows.get(member.id, []):
            start = max(start, claim_start.astimezone(tz))
            end = min(end, claim_end.astimezone(tz))
        amount, scope, claim = budgets.get(member.id, (None, None, None))
        context.members.append(MemberWindow(
            member_id=member.id, start=max(start, room_start), end=min(end, room_end),
            allow_solo=bool(row.allow_solo) if row else False,
            budget_cny=amount, budget_scope=scope,
            budget_claim_id=claim.id if claim is not None else None,
            avoid_keys=frozenset(avoids.get(member.id, set())),
            max_walking_km=walking.get(member.id),
            participation_id=participation_id, has_participation=has_participation))

    for fact in facts:
        context.slots.append(_slot(fact, room, context, tz))
    return context


def _slot(fact: ActivityFact, room: Room, context: PlanContext, tz) -> ActivitySlot:
    place = places.find(place_id=fact.place_id, place_name=fact.place_name, city=room.destination)
    duration = max(int(fact.duration_minutes or 60), MIN_ACTIVITY_MINUTES)
    window_start = _dt(fact.window_start)
    window_end = _dt(fact.window_end)
    reserved = _dt(fact.reserved_start)

    earliest = window_start.astimezone(tz) if window_start else datetime.combine(
        room.start_date, DAY_START, tzinfo=tz)
    latest_end = window_end.astimezone(tz) if window_end else datetime.combine(
        room.end_date, DAY_END, tzinfo=tz)

    fixed_start = None
    if reserved:
        fixed_start = reserved.astimezone(tz)
        earliest = max(earliest, fixed_start)
        latest_end = min(latest_end, fixed_start + timedelta(minutes=duration))
    elif fact.reservation_status == "confirmed":
        # A confirmed booking without a time still has to keep its duration,
        # but we cannot place it precisely; surface that instead of guessing.
        context.unknowns.append(f"{fact.name}：已确认预约但未提供时间")

    opening_known = place is not None
    if place is not None:
        if place.open_windows and not place.all_day:
            day = earliest.astimezone(tz).date()
            open_start = datetime.combine(day, place.open_windows[0][0], tzinfo=tz)
            open_end = datetime.combine(day, place.open_windows[-1][1], tzinfo=tz)
            earliest = max(earliest, open_start)
            latest_end = min(latest_end, open_end)
    else:
        context.unknowns.append(f"{fact.name}：缺少开放时间资料")

    return ActivitySlot(
        activity_id=fact.id, name=fact.name, place_name=fact.place_name, place_id=fact.place_id,
        duration_minutes=duration, earliest=earliest, latest_end=latest_end, fixed_start=fixed_start,
        cost_cny=float(fact.estimated_cost_cny or 0), cost_scope=fact.cost_scope,
        open_windows=place.open_windows if place else (),
        closed_weekdays=place.closed_weekdays if place else frozenset(),
        all_day=place.all_day if place else False,
        latitude=place.latitude if place else None, longitude=place.longitude if place else None,
        owner_member_id=fact.owner_member_id, source_note=fact.source_note,
        reservation_status=fact.reservation_status, opening_known=opening_known,
        travel_known=place is not None and place.located)
