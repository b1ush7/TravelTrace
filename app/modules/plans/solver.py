"""Constraint-aware schedule solver.

Pure functions over `PlanContext`: no Session, no ORM, no HTTP. The search is a
time-window subset DP over `(visited_mask, day, last_slot)`, which is exact for
"earliest finish" and fast enough for the 12-activity cap the API enforces.

Only activities every active member can attend are placed on the shared
timeline. Anything the group cannot attend together is excluded and reported,
because silently dropping a member from `member_ids` produced schedules that
nobody could actually join.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from app.modules.plans.context import ActivitySlot, MemberWindow, PlanContext
from app.modules.plans.travel import travel_minutes

MAX_ACTIVITIES = 12
NONE = -1
# When a member's own window is narrower than the activity window, the whole
# group has to fit inside the overlap. Otherwise the DP would schedule a
# 09:00 activity for someone who only arrives at 10:00.
COVER_TOLERANCE_MINUTES = 0


@dataclass
class PlannedItem:
    slot: ActivitySlot | None
    start: datetime
    end: datetime
    member_ids: list
    kind: str = "activity"
    title: str = ""
    place_name: str = ""
    branch_id: str | None = None

    @property
    def activity_id(self):
        return self.slot.activity_id if self.slot is not None else None


@dataclass
class ExcludedActivity:
    slot: ActivitySlot
    code: str
    message: str
    member_ids: list = field(default_factory=list)
    blocking: bool = False


@dataclass
class SolveResult:
    items: list[PlannedItem]
    excluded: list[ExcludedActivity]
    unknowns: list[str]
    unplaced: list[ActivitySlot]
    data_missing: bool = False

    @property
    def places_all(self) -> bool:
        return not self.unplaced and not any(item.blocking for item in self.excluded)


def _align_to_opening(slot: ActivitySlot, moment: datetime) -> datetime:
    """Push `moment` to the next moment the place accepts visitors."""
    if not slot.open_windows or slot.all_day:
        return moment
    day = moment.date()
    windows = sorted(slot.open_windows)
    for start, end in windows:
        open_at = datetime.combine(day, start, tzinfo=moment.tzinfo)
        close_at = datetime.combine(day, end, tzinfo=moment.tzinfo)
        if moment <= open_at:
            return open_at
        if moment < close_at:
            return moment
    return datetime.combine(day + timedelta(days=1), windows[0][0], tzinfo=moment.tzinfo)


def _fits_opening(slot: ActivitySlot, start: datetime) -> bool:
    if not slot.open_windows or slot.all_day:
        return True
    end = start + timedelta(minutes=slot.duration_minutes)
    if start.date() != end.date():
        return False
    for open_start, open_end in slot.open_windows:
        window_start = datetime.combine(start.date(), open_start, tzinfo=start.tzinfo)
        window_end = datetime.combine(start.date(), open_end, tzinfo=start.tzinfo)
        if window_start <= start and end <= window_end:
            return True
    return False


def _closed_on(slot: ActivitySlot, day) -> bool:
    return day.weekday() in slot.closed_weekdays


def _shared_bounds(slot: ActivitySlot, members: list[MemberWindow]) -> tuple[datetime, datetime]:
    """Intersection of the activity window with the availability of members who can reach it.

    A member whose window never overlaps the activity is reported as absent by
    the caller instead of collapsing this range to zero width, which used to
    hide a blocking conflict behind an empty span. Members who avoid the place
    are handled separately for the same reason.
    """
    attending = [item for item in members
                 if slot.resolved_place_key not in item.avoid_keys
                 and item.overlap(slot.earliest, slot.latest_end)]
    if not attending:
        return slot.earliest, slot.earliest
    lower = [slot.earliest] + [item.start for item in attending]
    upper = [slot.latest_end] + [item.end for item in attending]
    # Opening hours cap the shared span too, otherwise a 19:00 activity window
    # would make a place that closes at 17:00 look available all evening.
    if slot.open_windows and not slot.all_day:
        open_start = min(start for start, _end in slot.open_windows)
        open_end = max(end for _start, end in slot.open_windows)
        lower.append(datetime.combine(slot.earliest.date(), open_start, tzinfo=slot.earliest.tzinfo))
        upper.append(datetime.combine(slot.earliest.date(), open_end, tzinfo=slot.earliest.tzinfo))
    start = max(lower)
    end = min(upper)
    return start, end


def shared_members(slot: ActivitySlot, members: list[MemberWindow],
                   start: datetime | None = None, end: datetime | None = None) -> list[MemberWindow]:
    """Members who can attend this activity in the given (or widest) time range."""
    if start is None or end is None:
        span_start, span_end = _shared_bounds(slot, members)
    else:
        span_start, span_end = start, end
    return [item for item in members
            if slot.resolved_place_key not in item.avoid_keys
            and item.covers(span_start + timedelta(minutes=COVER_TOLERANCE_MINUTES),
                            span_end - timedelta(minutes=COVER_TOLERANCE_MINUTES))]


def _ceil_to_minute(moment: datetime) -> datetime:
    if moment.second or moment.microsecond:
        return (moment + timedelta(minutes=1)).replace(second=0, microsecond=0)
    return moment


def solve(context: PlanContext, *, allow_split: bool = False,
          locked: list[PlannedItem] | None = None) -> SolveResult:
    """Place every shared activity on a civilised timeline inside the room window."""
    members = context.members
    all_ids = [item.member_id for item in members]
    excluded: list[ExcludedActivity] = []
    unknowns = list(context.unknowns)
    data_missing = context.data_missing

    shared: list[ActivitySlot] = []
    for slot in context.slots:
        if not slot.opening_known:
            data_missing = True
        start, end = _shared_bounds(slot, members)
        attendees = shared_members(slot, members, start, end)
        if len(attendees) == len(members) and attendees:
            shared.append(slot)
            continue

        # Two different reasons a member stays out of the shared slot: they
        # avoid the place outright, or their window cannot cover it. Both are
        # reported; only the second is something they could relax.
        avoiding = [item for item in members if slot.resolved_place_key in item.avoid_keys]
        absent = [item for item in members if item not in attendees and item not in avoiding]
        blockers = [item for item in absent if not item.allow_solo]
        if slot.resolved_place_key and avoiding:
            unknowns.append(f"{slot.name}：有成员明确回避该地点")
            excluded.append(ExcludedActivity(
                slot=slot, code="PLACE_AVOIDED",
                message=f"{slot.name} 与成员的回避条件冲突，已移出共同行程",
                member_ids=[item.member_id for item in avoiding], blocking=True))
            continue
        if not allow_split and blockers:
            excluded.append(ExcludedActivity(
                slot=slot, code="MEMBER_TIME_CONFLICT",
                message=f"{slot.name} 无法安排：{len(blockers)} 位成员时间不重叠且不接受分头",
                member_ids=[item.member_id for item in blockers], blocking=True))
        else:
            mode = "分头" if allow_split else "可自由活动"
            excluded.append(ExcludedActivity(
                slot=slot, code="NOT_SHARED",
                message=f"{slot.name} 全员无法同场，已按{mode}处理",
                member_ids=[item.member_id for item in absent + avoiding]))
        unknowns.append(f"{slot.name}：全员时间窗不重叠")

    if len(shared) > MAX_ACTIVITIES:
        shared = shared[:MAX_ACTIVITIES]
        unknowns.append(f"候选活动超过 {MAX_ACTIVITIES} 个，已截断")

    placed, unplaced = _search(context, shared, members)
    if unplaced:
        unknowns.append("、".join(item.name for item in unplaced) + "：时间窗内排不下")

    items = _materialize(context, placed, all_ids, members)
    return SolveResult(items=items, excluded=excluded, unknowns=unknowns, unplaced=unplaced,
                       data_missing=data_missing)


def _search(context: PlanContext, slots: list[ActivitySlot], members: list[MemberWindow]):
    """DP over (mask, day, last) -> earliest finish; predecessors remember choices."""
    n = len(slots)
    if n == 0:
        return [], []

    day_count = max(context.days, 1)
    best: dict[tuple[int, int, int], datetime] = {}
    choice: dict[tuple[int, int, int], tuple[tuple[int, int, int] | None, datetime]] = {}

    def relax(key, finish, previous, start) -> None:
        if best.get(key) is None or finish < best[key]:
            best[key] = finish
            choice[key] = (previous, start)

    def feasible(slot: ActivitySlot, start: datetime) -> bool:
        """The group must fit in the slot's window, the opening hours and every member."""
        end = start + timedelta(minutes=slot.duration_minutes)
        if end > slot.latest_end:
            return False
        if slot.fixed_start is not None and start != slot.fixed_start:
            return False
        if not _fits_opening(slot, start):
            return False
        bound_start, bound_end = _shared_bounds(slot, members)
        if start < bound_start or end > bound_end:
            return False
        return True

    def candidate_start(slot: ActivitySlot, floor: datetime) -> datetime:
        """Earliest legal start at or after `floor`, honouring a fixed booking.

        The shared lower bound matters: if one member only arrives at 10:00 the
        activity cannot start at 09:00 just because the day does.
        """
        if slot.fixed_start is not None:
            return slot.fixed_start
        bound_start, _bound_end = _shared_bounds(slot, members)
        return _ceil_to_minute(max(floor, slot.earliest, bound_start,
                                   _align_to_opening(slot, max(floor, bound_start))))

    # Seeds: any activity may open the day it fits.
    for day in range(day_count):
        day_start, day_end = context.day_bounds(day)
        for index, slot in enumerate(slots):
            if _closed_on(slot, day_start.date()):
                continue
            if slot.fixed_start is not None and slot.fixed_start.date() != day_start.date():
                continue
            start = candidate_start(slot, day_start)
            if not feasible(slot, start):
                continue
            finish = start + timedelta(minutes=slot.duration_minutes)
            if finish > day_end:
                continue
            relax((1 << index, day, index), finish, None, start)

    # Increasing popcount guarantees every predecessor is final before use.
    for size in range(1, n):
        for mask in range(1, 1 << n):
            if bin(mask).count("1") != size:
                continue
            for day in range(day_count):
                day_date = context.day_bounds(day)[0].date()
                _, day_end = context.day_bounds(day)
                for last in range(n):
                    end = best.get((mask, day, last))
                    if end is None:
                        continue
                    for nxt in range(n):
                        if mask >> nxt & 1:
                            continue
                        slot = slots[nxt]
                        if _closed_on(slot, day_date):
                            continue
                        if slot.fixed_start is not None and slot.fixed_start.date() != day_date:
                            continue
                        minutes, _source = travel_minutes(slots[last], slot)
                        if minutes is None:
                            continue
                        arrival = end + timedelta(minutes=minutes)
                        start = candidate_start(slot, arrival)
                        if not feasible(slot, start):
                            continue
                        finish = start + timedelta(minutes=slot.duration_minutes)
                        if finish > day_end:
                            continue
                        relax((mask | 1 << nxt, day, nxt), finish, (mask, day, last), start)

    # Prefer the state that covers the most activities, then the earliest finish.
    best_state = None
    for (mask, day, last), end in best.items():
        if last == NONE:
            continue
        score = (bin(mask).count("1"), -end.timestamp())
        if best_state is None or score > best_state[0]:
            best_state = (score, mask, day, last)

    if best_state is None:
        return [], list(slots)

    _, mask, day, last = best_state
    chain: list[tuple[int, datetime]] = []
    seen: set[tuple[int, int, int]] = set()
    while last != NONE:
        key = (mask, day, last)
        if key in seen:
            break
        seen.add(key)
        previous, start = choice[key]
        chain.append((last, start))
        if previous is None:
            break
        mask, day, last = previous
    chain.reverse()

    placed = [(slots[index], start) for index, start in chain]
    placed_ids = {slot.activity_id for slot, _ in placed}
    unplaced = [slot for slot in slots if slot.activity_id not in placed_ids]
    return placed, unplaced


def _materialize(context: PlanContext, placed: list[tuple[ActivitySlot, datetime]],
                 all_ids: list, members: list[MemberWindow]) -> list[PlannedItem]:
    items: list[PlannedItem] = []
    if placed:
        first_slot, first_start = placed[0]
        origin = datetime.combine(context.start_date, time(8, 30), tzinfo=context.tz)
        items.append(PlannedItem(
            slot=None, start=origin, end=min(first_start, origin + timedelta(minutes=30)),
            member_ids=list(all_ids), kind="meeting", title="集合出发",
            place_name=first_slot.place_name))
    for slot, start in placed:
        end = start + timedelta(minutes=slot.duration_minutes)
        attendees = [item.member_id for item in shared_members(slot, members, start, end)]
        items.append(PlannedItem(
            slot=slot, start=start, end=end, member_ids=attendees or list(all_ids),
            kind="activity", title=slot.name, place_name=slot.place_name))
    items.sort(key=lambda item: item.start)
    return items
