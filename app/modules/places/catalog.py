"""Location facts used by the planner.

The demo entries below used to live as Chinese prose inside places/router.py
(\"​09:00–17:00，周一闭馆\"). The planner needs opening windows, closed
weekdays and coordinates as data, so they are parsed once here into structured
fields. `opening_hours` keeps the original prose for the API response.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timezone

_VERIFIED = datetime(2026, 11, 1, tzinfo=timezone.utc)

_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
_HHMM = re.compile(r"(\d{1,2}):(\d{2})")


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    city: str
    address: str | None
    latitude: float | None
    longitude: float | None
    opening_hours: str | None
    open_windows: tuple[tuple[time, time], ...] = ()
    closed_weekdays: frozenset[int] = frozenset()
    all_day: bool = False
    price_cny: float | None = None
    source: str = "demo-catalog"
    verified_at: datetime | None = _VERIFIED

    @property
    def located(self) -> bool:
        return self.latitude is not None and self.longitude is not None


def parse_opening_hours(text: str | None) -> tuple[tuple[tuple[time, time], ...], frozenset[int], bool]:
    """Turn '​09:00–17:00，周一闭馆' into windows + closed weekdays + all_day.

    Only the shapes used by the demo catalog are handled: "HH:MM-HH:MM" ranges
    separated by punctuation, "周一闭馆" style closure notes, and the
    literal "全天". Anything unrecognised yields no windows, which the solver
    reports as missing evidence rather than assuming 24h availability.
    """
    if not text:
        return (), frozenset(), False
    lowered = text.strip()
    if lowered in {"全天", "24 小时", "24小时"}:
        return (), frozenset(), True

    windows: list[tuple[time, time]] = []
    for start_raw, end_raw in re.findall(r"(\d{1,2}:\d{2})\s*[–—\-~～]\s*(\d{1,2}:\d{2})", text):
        try:
            start = time.fromisoformat(start_raw)
            end = time.fromisoformat(end_raw)
        except ValueError:
            continue
        if start < end:
            windows.append((start, end))

    closed: set[int] = set()
    for marker in re.findall(r"周([一二三四五六日])闭馆", text):
        closed.add(_WEEKDAYS[marker])
    if "法定节假日除外" in text:
        # "Monday closed except public holidays" - we cannot evaluate the
        # holiday calendar, so keep the closure and let callers warn.
        pass
    return tuple(windows), frozenset(closed), False


def _place(place_id: str, name: str, city: str, address: str, lat: float, lon: float,
           hours: str, price: float) -> Place:
    windows, closed, all_day = parse_opening_hours(hours)
    return Place(id=place_id, name=name, city=city, address=address, latitude=lat,
                 longitude=lon, opening_hours=hours, open_windows=windows,
                 closed_weekdays=closed, all_day=all_day, price_cny=price)


_PLACES: tuple[Place, ...] = (
    _place("xian-balu", "八路军西安办事处纪念馆", "西安",
           "新城区北新街七贤庄一号", 34.2691, 108.9582, "09:00–17:00，周一闭馆", 0),
    _place("xian-incident", "西安事变纪念馆（张学良公馆）", "西安",
           "碑林区建国路69号", 34.2573, 108.9686, "09:00–17:00，周一闭馆", 0),
    _place("xian-zhiyuan", "杨虎城将军纪念馆（止园）", "西安",
           "莲湖区青年路117号", 34.2708, 108.9401, "09:00–17:00，周一闭馆", 0),
    _place("xian-revolution-park", "革命公园", "西安",
           "新城区西五路53号", 34.2701, 108.9513, "06:00–21:00", 0),
    _place("xian-martyrs", "西安烈士陵园", "西安",
           "雁塔区含光路南段", 34.2189, 108.9276, "09:00–17:00，周一闭馆", 0),
    _place("xian-wall", "西安城墙（永宁门）", "西安",
           "碑林区南大街2号", 34.2541, 108.9422, "08:00–22:00", 54),
    _place("xian-museum", "陕西历史博物馆", "西安",
           "雁塔区小寨东路91号", 34.2226, 108.9531, "08:30–18:00，周一闭馆", 0),
    _place("chengdu-kuanzhai", "宽窄巷子", "成都",
           "青羊区长顺上街", 30.6636, 104.0549, "全天", 0),
    _place("chengdu-renmin", "人民公园", "成都",
           "青羊区少城路12号", 30.6572, 104.0553, "06:00–22:00", 0),
)

BY_ID = {item.id: item for item in _PLACES}
BY_NAME = {item.name: item for item in _PLACES}


def all_places() -> tuple[Place, ...]:
    return _PLACES


def find(*, place_id: str | None = None, place_name: str | None = None, city: str | None = None) -> Place | None:
    if place_id and place_id in BY_ID:
        return BY_ID[place_id]
    if place_name and place_name in BY_NAME:
        return BY_NAME[place_name]
    for item in _PLACES:
        if city and item.city != city:
            continue
        if place_name and item.name == place_name:
            return item
    return None


def places_in_city(city: str) -> list[Place]:
    return [item for item in _PLACES if item.city == city]
