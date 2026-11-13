from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

# Demo content. Every fact carries a source and an observation time; entries we
# could not verify are marked verified=false instead of being silently invented.
FACT_MAX_AGE_DAYS = 180


def _uid(kind: str, key: str):
    return str(uuid5(NAMESPACE_URL, f"traveltrace:{kind}:{key}"))


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


OBSERVED_AT = _dt("2026-11-01T00:00:00+08:00")
UPDATED_AT = _dt("2026-11-01T00:00:00+08:00")


def _fact(theme: str, key: str, category: str, title: str, place: str, value: str,
          source: str, *, verified: bool = True, place_id: str | None = None) -> dict:
    age = datetime.now(timezone.utc) - OBSERVED_AT
    return {
        "id": _uid("theme-fact", key),
        "category": category,
        "title": title,
        "place_name": place,
        "place_id": place_id,
        "value": value,
        "source": source,
        "observed_at": OBSERVED_AT,
        "verified": verified,
        "stale": age > timedelta(days=FACT_MAX_AGE_DAYS),
    }


_PLACES = {
    "balu": _uid("place", "xian-balu"),
    "xian_incident": _uid("place", "xian-incident"),
    "zhiyuan": _uid("place", "xian-zhiyuan"),
    "revolution_park": _uid("place", "xian-revolution-park"),
    "martyrs": _uid("place", "xian-martyrs"),
}

_RED_RULES = [
    {"code": "RED_MONDAY_CLOSED", "description": "多数纪念馆周一闭馆，出发前按馆核实", "severity": "error", "applies_to": "activity"},
    {"code": "RED_DOCENT_BOOKING", "description": "团队讲解需提前预约，场次固定", "severity": "warning", "applies_to": "activity"},
    {"code": "RED_REALNAME_LIMIT", "description": "部分场馆实名预约并限流，需携带身份证", "severity": "error", "applies_to": "activity"},
    {"code": "RED_ETIQUETTE", "description": "肃穆场所着装得体，禁止喧哗，部分展厅禁止拍照", "severity": "warning", "applies_to": "activity"},
]

_RED_FACTS = [
    _fact("red_tour", "balu-opening", "opening", "开放时间", "八路军西安办事处纪念馆",
          "09:00–17:00，16:30 停止入馆；周一闭馆（法定节假日除外）",
          "八路军西安办事处纪念馆官网 2026-11-01 公告", place_id=_PLACES["balu"]),
    _fact("red_tour", "balu-ticket", "ticket", "门票", "八路军西安办事处纪念馆",
          "免费，需预约", "场馆官网 2026-11-01", place_id=_PLACES["balu"]),
    _fact("red_tour", "balu-reservation", "reservation", "预约方式", "八路军西安办事处纪念馆",
          "官方公众号实名预约，个人可约当日，团队需提前 3 个工作日",
          "场馆公众号 2026-11-01", place_id=_PLACES["balu"]),
    _fact("red_tour", "balu-docent", "docent", "讲解场次", "八路军西安办事处纪念馆",
          "固定场次 10:00、14:30；团队讲解需提前预约",
          "场馆公告 2026-11-01", place_id=_PLACES["balu"]),
    _fact("red_tour", "xian-incident-opening", "opening", "开放时间", "西安事变纪念馆（张学良公馆）",
          "09:00–17:00，周一闭馆", "西安事变纪念馆官网 2026-11-01", place_id=_PLACES["xian_incident"]),
    _fact("red_tour", "xian-incident-ticket", "ticket", "门票", "西安事变纪念馆（张学良公馆）",
          "免费，凭身份证换票", "场馆官网 2026-11-01", place_id=_PLACES["xian_incident"]),
    _fact("red_tour", "xian-incident-docent", "docent", "讲解场次", "西安事变纪念馆（张学良公馆）",
          "10:00、15:00 两场；节假日视客流加场", "场馆公告 2026-11-01", place_id=_PLACES["xian_incident"]),
    _fact("red_tour", "zhiyuan-opening", "opening", "开放时间", "杨虎城将军纪念馆（止园）",
          "09:00–17:00，周一闭馆", "西安市文旅局 2026-11-01", place_id=_PLACES["zhiyuan"]),
    _fact("red_tour", "zhiyuan-ticket", "ticket", "门票", "杨虎城将军纪念馆（止园）",
          "免费", "场馆官网 2026-11-01", place_id=_PLACES["zhiyuan"]),
    _fact("red_tour", "park-opening", "opening", "开放时间", "革命公园",
          "06:00–21:00，全年开放", "公园公告 2026-11-01", place_id=_PLACES["revolution_park"]),
    _fact("red_tour", "park-ticket", "ticket", "门票", "革命公园", "免费", "公园公告 2026-11-01",
          place_id=_PLACES["revolution_park"]),
    _fact("red_tour", "martyrs-opening", "opening", "开放时间", "西安烈士陵园",
          "09:00–17:00，周一闭馆", "陵园公告 2026-11-01", place_id=_PLACES["martyrs"]),
    _fact("red_tour", "martyrs-reservation", "reservation", "团队预约", "西安烈士陵园",
          "团队需提前 3 个工作日预约，个人登记入内", "陵园公告 2026-11-01", place_id=_PLACES["martyrs"]),
    _fact("red_tour", "martyrs-etiquette", "etiquette", "礼仪提示", "西安烈士陵园",
          "着装素雅，保持安静，纪念区禁止拍照与嬉闹", "陵园公告 2026-11-01", place_id=_PLACES["martyrs"]),
    _fact("red_tour", "transport-note", "transport", "交通耗时", "西安事变纪念馆（张学良公馆）",
          "从钟楼打车约 15 分钟；地铁 4 号线大差市站步行约 800 米",
          "待核实：需按当日路况校准", verified=False, place_id=_PLACES["xian_incident"]),
]

_RED_ITEMS_2D = [
    {"place_name": "八路军西安办事处纪念馆", "place_id": _PLACES["balu"], "duration_minutes": 90, "estimated_cost_cny": 0, "window_start": "09:00", "window_end": "11:30"},
    {"place_name": "西安事变纪念馆（张学良公馆）", "place_id": _PLACES["xian_incident"], "duration_minutes": 75, "estimated_cost_cny": 0, "window_start": "13:30", "window_end": "16:30"},
    {"place_name": "革命公园", "place_id": _PLACES["revolution_park"], "duration_minutes": 60, "estimated_cost_cny": 0, "window_start": "16:30", "window_end": "18:00"},
    {"place_name": "杨虎城将军纪念馆（止园）", "place_id": _PLACES["zhiyuan"], "duration_minutes": 60, "estimated_cost_cny": 0, "window_start": "09:00", "window_end": "11:30"},
    {"place_name": "西安烈士陵园", "place_id": _PLACES["martyrs"], "duration_minutes": 60, "estimated_cost_cny": 0, "window_start": "14:00", "window_end": "16:30"},
]

_RED_ITEMS_3D = _RED_ITEMS_2D + [
    {"place_name": "八路军西安办事处纪念馆", "place_id": _PLACES["balu"], "duration_minutes": 120, "estimated_cost_cny": 0, "window_start": "09:00", "window_end": "12:00"},
]

_THEMES = {
    "red_tour": {
        "code": "red_tour",
        "name": "红色西安",
        "summary": "用两天走完西安五处可核验的红色点位，按闭馆日与讲解场次排程。",
        "cover_url": "https://static.traveltrace.demo/themes/red_tour.jpg",
        "domains": ["red", "culture", "history"],
        "city_scope": "西安",
        "is_demo": True,
        "status": "active",
        "updated_at": UPDATED_AT,
        "rules": _RED_RULES,
        "facts": _RED_FACTS,
        "packs": [
            {
                "id": _uid("theme-pack", "red_tour-2d"),
                "theme_code": "red_tour",
                "name": "红色西安 2 天骨架",
                "days": 2,
                "city": "西安",
                "items": _RED_ITEMS_2D,
                "suitable_group": "3–6 人小团、党支部/研学小队",
                "notes": "周一多数场馆闭馆；团队讲解需提前 3 个工作日预约。",
            },
            {
                "id": _uid("theme-pack", "red_tour-3d"),
                "theme_code": "red_tour",
                "name": "红色西安 3 天慢行",
                "days": 3,
                "city": "西安",
                "items": _RED_ITEMS_3D,
                "suitable_group": "时间宽裕、希望加入讨论环节的小团",
                "notes": "第三天留出复盘与自由交流时间。",
            },
        ],
    },
    "city_walk_xian": {
        "code": "city_walk_xian",
        "name": "西安城市漫步",
        "summary": "城墙、老巷与街角咖啡，适合不赶时间的半日慢行。",
        "cover_url": None,
        "domains": ["photo", "culture", "food"],
        "city_scope": "西安",
        "is_demo": False,
        "status": "active",
        "updated_at": UPDATED_AT,
        "rules": [
            {"code": "WALK_HEAT", "description": "夏季午后高温，建议避开 13:00–15:00 暴晒时段", "severity": "warning", "applies_to": "activity"},
        ],
        "facts": [
            _fact("city_walk_xian", "wall-opening", "opening", "城墙开放时间", "西安城墙",
                  "08:00–22:00，各门点关闭时间不同", "西安城墙景区公告 2026-11-01"),
            _fact("city_walk_xian", "wall-ticket", "ticket", "门票", "西安城墙",
                  "54 元/人，学生半价", "景区官网 2026-11-01"),
        ],
        "packs": [{
            "id": _uid("theme-pack", "city_walk_xian-1d"),
            "theme_code": "city_walk_xian", "name": "城墙到老巷 1 天", "days": 1, "city": "西安",
            "items": [
                {"place_name": "西安城墙（永宁门）", "place_id": None, "duration_minutes": 120, "estimated_cost_cny": 54, "window_start": "09:00", "window_end": "12:00"},
                {"place_name": "书院门与老巷", "place_id": None, "duration_minutes": 90, "estimated_cost_cny": 0, "window_start": "14:00", "window_end": "17:00"},
            ],
            "suitable_group": "朋友、情侣", "notes": "步行较多，穿舒适的鞋。",
        }],
    },
    "food_chengdu": {
        "code": "food_chengdu",
        "name": "成都吃到扶墙",
        "summary": "一天四顿的成都老城美食路线，兼顾口味清淡的同伴。",
        "cover_url": None,
        "domains": ["food", "culture"],
        "city_scope": "成都",
        "is_demo": False,
        "status": "active",
        "updated_at": UPDATED_AT,
        "rules": [
            {"code": "FOOD_SPICY", "description": "多数菜品偏辣，点单时确认微辣/不辣", "severity": "info", "applies_to": "activity"},
        ],
        "facts": [
            _fact("food_chengdu", "hotpot-hours", "opening", "营业时间", "成都老火锅（示例）",
                  "11:00–次日 02:00", "商家公开信息 2026-11-01", verified=False),
        ],
        "packs": [{
            "id": _uid("theme-pack", "food_chengdu-1d"),
            "theme_code": "food_chengdu", "name": "成都老城 1 天四顿", "days": 1, "city": "成都",
            "items": [
                {"place_name": "宽窄巷子小吃", "place_id": None, "duration_minutes": 60, "estimated_cost_cny": 60, "window_start": "09:00", "window_end": "11:00"},
                {"place_name": "人民公园盖碗茶", "place_id": None, "duration_minutes": 90, "estimated_cost_cny": 40, "window_start": "14:00", "window_end": "16:00"},
                {"place_name": "成都老火锅（示例）", "place_id": None, "duration_minutes": 120, "estimated_cost_cny": 120, "window_start": "18:00", "window_end": "20:30"},
            ],
            "suitable_group": "吃货小队", "notes": "预留排队时间。",
        }],
    },
}


def _theme_card(theme: dict) -> dict:
    return {
        "code": theme["code"],
        "name": theme["name"],
        "summary": theme["summary"],
        "cover_url": theme["cover_url"],
        "domains": theme["domains"],
        "city_scope": theme["city_scope"],
        "fact_count": sum(1 for fact in theme["facts"] if fact["verified"]),
        "pack_count": len(theme["packs"]),
        "is_demo": theme["is_demo"],
        "status": theme["status"],
        "updated_at": theme["updated_at"],
    }


def list_themes(domain: str | None = None, city: str | None = None) -> list[dict]:
    themes = sorted(_THEMES.values(), key=lambda item: (not item["is_demo"], item["code"]))
    result = []
    for theme in themes:
        if theme["status"] != "active":
            continue
        if domain and domain not in theme["domains"]:
            continue
        if city and city != theme["city_scope"]:
            continue
        result.append(_theme_card(theme))
    return result[:50]


def get_theme(theme_code: str) -> dict | None:
    theme = _THEMES.get(theme_code)
    if theme is None:
        return None
    return {
        "theme": _theme_card(theme),
        "rules": theme["rules"],
        "facts": theme["facts"],
    }


def get_packs(theme_code: str) -> list[dict] | None:
    theme = _THEMES.get(theme_code)
    return None if theme is None else theme["packs"]


def exists(theme_code: str) -> bool:
    return theme_code in _THEMES


def city_scope(theme_code: str) -> str | None:
    theme = _THEMES.get(theme_code)
    return None if theme is None else theme["city_scope"]


def name(theme_code: str) -> str | None:
    theme = _THEMES.get(theme_code)
    return None if theme is None else theme["name"]


def badge(theme_code: str) -> str | None:
    theme = _THEMES.get(theme_code)
    if theme is None:
        return None
    return "Demo 主题" if theme["is_demo"] else "主题游"


def rules(theme_code: str) -> list[dict]:
    theme = _THEMES.get(theme_code)
    return [] if theme is None else theme["rules"]


def facts(theme_code: str) -> list[dict]:
    theme = _THEMES.get(theme_code)
    return [] if theme is None else theme["facts"]
