"""Solver-level units: pure functions, no database, no HTTP.

These pin the constraints that the old planner claimed to honour but ignored:
activity windows, confirmed reservations, member participation windows, travel
estimation and per-person cost scope.
"""

from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.modules.places.catalog import parse_opening_hours
from app.modules.plans.context import ActivitySlot, MemberWindow, PlanContext
from app.modules.plans.solver import shared_members, solve
from app.modules.plans.travel import UNKNOWN_TRAVEL_MINUTES, travel_minutes

TZ = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 12, 5)  # a Saturday
M1, M2 = uuid4(), uuid4()


def slot(name, duration, window_start, window_end, *, fixed=None, place_id=None,
         open_windows=((time(9, 0), time(17, 0)),), closed=frozenset(),
         lat=34.26, lon=108.95, cost=0.0, scope="per_person"):
    return ActivitySlot(
        activity_id=uuid4(), name=name, place_name=name, place_id=place_id,
        duration_minutes=duration,
        earliest=datetime.combine(DAY, window_start, tzinfo=TZ),
        latest_end=datetime.combine(DAY, window_end, tzinfo=TZ),
        fixed_start=fixed, cost_cny=cost, cost_scope=scope,
        open_windows=open_windows, closed_weekdays=closed,
        latitude=lat, longitude=lon, opening_known=True)


def member(member_id=M1, start=time(9, 0), end=time(19, 0), *, allow_solo=False,
           avoid=frozenset(), budget=None):
    return MemberWindow(
        member_id=member_id,
        start=datetime.combine(DAY, start, tzinfo=TZ),
        end=datetime.combine(DAY, end, tzinfo=TZ),
        allow_solo=allow_solo, avoid_keys=avoid, budget_cny=budget,
        has_participation=True)


def context(members, slots):
    return PlanContext(room_id=uuid4(), start_date=DAY, end_date=DAY, tz=TZ,
                       members=members, slots=slots)


def titles(result):
    return [item.title for item in result.items if item.kind == "activity"]


def test_opening_hours_are_parsed_into_data():
    windows, closed, all_day = parse_opening_hours("09:00–17:00，周一闭馆")
    assert windows == ((time(9, 0), time(17, 0)),)
    assert closed == frozenset({0})
    assert all_day is False

    windows, closed, all_day = parse_opening_hours("全天")
    assert windows == () and closed == frozenset() and all_day is True

    # Unrecognised prose must not be treated as around-the-clock access.
    windows, _closed, all_day = parse_opening_hours("见官网公告")
    assert windows == () and all_day is False


def test_activity_window_is_respected():
    result = solve(context([member(), member(M2)], [slot("A", 60, time(9, 0), time(11, 0))]))
    assert titles(result) == ["A"]
    assert result.items[1].start.hour == 9


def test_activity_that_cannot_fit_its_window_is_reported():
    # The activity window is 09:00-10:00 but the visit takes 120 minutes.
    result = solve(context([member(), member(M2)], [slot("Long", 120, time(9, 0), time(10, 0))]))
    assert titles(result) == []
    assert [item.name for item in result.unplaced] == ["Long"]
    assert result.places_all is False
    assert any("Long" in message for message in result.unknowns)


def test_activity_window_alone_does_not_hide_a_shared_slot():
    # The activity window is wide open; the place is what limits it. M1 arrives
    # at 10:00, so the group can still meet inside 10:00-19:00.
    late = member(M1, start=time(10, 0))
    result = solve(context([late, member(M2)], [slot("Early", 60, time(9, 0), time(19, 0))]))
    assert titles(result) == ["Early"]
    activity = next(item for item in result.items if item.kind == "activity")
    assert activity.start.hour >= 10


def test_confirmed_reservation_keeps_its_booked_time():
    booked = datetime.combine(DAY, time(14, 0), tzinfo=TZ)
    result = solve(context([member(), member(M2)],
                           [slot("Reserved", 90, time(9, 0), time(19, 0), fixed=booked)]))
    assert titles(result) == ["Reserved"]
    activity = next(item for item in result.items if item.kind == "activity")
    assert activity.start == booked
    assert activity.end == booked + timedelta(minutes=90)


def test_member_window_narrows_the_shared_slot():
    # M1 leaves at 11:00 and the activity window starts at 12:00, so there is
    # no overlap at all and the slot cannot be shared.
    early_leaver = member(M1, start=time(9, 0), end=time(11, 0))
    result = solve(context([early_leaver, member(M2)],
                           [slot("Afternoon", 60, time(12, 0), time(16, 0))]))
    assert titles(result) == []
    assert [item.code for item in result.excluded] == ["MEMBER_TIME_CONFLICT"]
    assert result.excluded[0].blocking is True
    assert result.places_all is False


def test_member_who_accepts_solo_is_not_blocking():
    late = member(M1, start=time(9, 0), end=time(11, 0), allow_solo=True)
    result = solve(context([late, member(M2)], [slot("Afternoon", 60, time(14, 0), time(16, 0))]))
    assert titles(result) == []
    assert [item.code for item in result.excluded] == ["NOT_SHARED"]
    assert result.excluded[0].blocking is False
    assert result.places_all is True


def test_avoided_place_is_excluded_even_when_times_overlap():
    avoiding = member(M1, avoid=frozenset({"banned"}))
    result = solve(context([avoiding, member(M2)],
                           [slot("Banned", 60, time(9, 0), time(19, 0), place_id="banned")]))
    assert [item.code for item in result.excluded] == ["PLACE_AVOIDED"]
    assert result.excluded[0].blocking is True
    assert result.places_all is False


def test_closed_weekday_is_skipped():
    monday = date(2026, 12, 7)
    slot_ = slot("Museum", 60, time(9, 0), time(17, 0), closed=frozenset({0}))
    ctx = PlanContext(room_id=uuid4(), start_date=monday, end_date=monday, tz=TZ,
                      members=[member(), member(M2)],
                      slots=[ActivitySlot(**{**slot_.__dict__, "earliest":
                                             datetime.combine(monday, time(9, 0), tzinfo=TZ),
                                             "latest_end": datetime.combine(monday, time(17, 0),
                                                                            tzinfo=TZ)})])
    result = solve(ctx)
    assert titles(result) == []


def test_chained_activities_respect_travel_and_order():
    a = slot("A", 90, time(9, 0), time(11, 30))
    b = slot("B", 75, time(13, 30), time(16, 30))
    c = slot("C", 30, time(16, 30), time(17, 0))
    result = solve(context([member(), member(M2)], [a, b, c]))
    assert titles(result) == ["A", "B", "C"]
    placed = [item for item in result.items if item.kind == "activity"]
    for first, second in zip(placed, placed[1:]):
        minutes, source = travel_minutes(
            next(s for s in (a, b, c) if s.name == first.title),
            next(s for s in (a, b, c) if s.name == second.title))
        assert minutes is not None
        assert first.end + timedelta(minutes=minutes) <= second.start


def test_travel_time_is_unknown_without_coordinates():
    # The meeting point has no coordinates, so the leg into the first activity
    # is reported as unknown instead of being invented.
    minutes, source = travel_minutes(None, slot("NoCoords", 60, time(9, 0), time(10, 0)))
    assert minutes is None and source == "unknown"
    first = slot("First", 60, time(9, 0), time(10, 0))
    second = slot("Second", 60, time(10, 0), time(11, 0), lat=None, lon=None)
    # A conservative placeholder keeps the timeline workable, but the source
    # stays 'unknown' so the plan cannot be published on this evidence.
    minutes, source = travel_minutes(first, second)
    assert minutes == UNKNOWN_TRAVEL_MINUTES and source == "unknown"


def test_travel_time_is_distance_based_not_constant():
    near = slot("Near", 30, time(9, 0), time(10, 0), lat=34.260, lon=108.950)
    far = slot("Far", 30, time(10, 0), time(11, 0), lat=34.219, lon=108.928)
    minutes, source = travel_minutes(near, far)
    assert source == "haversine_estimate"
    assert minutes is not None and minutes > 8


def test_shared_members_only_returns_members_covering_the_span():
    span = slot("Span", 60, time(9, 0), time(12, 0))
    start = datetime.combine(DAY, time(9, 0), tzinfo=TZ)
    end = datetime.combine(DAY, time(10, 0), tzinfo=TZ)
    attendees = shared_members(span, [member(M1, start=time(10, 0)), member(M2)], start, end)
    assert [item.member_id for item in attendees] == [M2]
