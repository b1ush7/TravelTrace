from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import ValidationError

from app.core.errors import ApiError
from app.modules.places.schemas import KnowledgeHitOut, PlaceOut
from app.modules.themes import catalog as themes

router = APIRouter(tags=["地点与知识"])

_VERIFIED = datetime(2026, 11, 1, tzinfo=timezone.utc)

_PLACES = [
    ("xian-balu", "八路军西安办事处纪念馆", "西安", "新城区北新街七贤庄一号", 34.2691, 108.9582, "09:00–17:00，周一闭馆", 0),
    ("xian-incident", "西安事变纪念馆（张学良公馆）", "西安", "碑林区建国路69号", 34.2573, 108.9686, "09:00–17:00，周一闭馆", 0),
    ("xian-zhiyuan", "杨虎城将军纪念馆（止园）", "西安", "莲湖区青年路117号", 34.2708, 108.9401, "09:00–17:00，周一闭馆", 0),
    ("xian-revolution-park", "革命公园", "西安", "新城区西五路53号", 34.2701, 108.9513, "06:00–21:00", 0),
    ("xian-martyrs", "西安烈士陵园", "西安", "雁塔区含光路南段", 34.2189, 108.9276, "09:00–17:00，周一闭馆", 0),
    ("xian-wall", "西安城墙（永宁门）", "西安", "碑林区南大街2号", 34.2541, 108.9422, "08:00–22:00", 54),
    ("xian-museum", "陕西历史博物馆", "西安", "雁塔区小寨东路91号", 34.2226, 108.9531, "08:30–18:00，周一闭馆", 0),
    ("chengdu-kuanzhai", "宽窄巷子", "成都", "青羊区长顺上街", 30.6636, 104.0549, "全天", 0),
    ("chengdu-renmin", "人民公园", "成都", "青羊区少城路12号", 30.6572, 104.0553, "06:00–22:00", 0),
]


def _place(row) -> PlaceOut:
    return PlaceOut(id=row[0], name=row[1], city=row[2], address=row[3], latitude=row[4],
                    longitude=row[5], coordinate_system="gcj02", source="demo-catalog",
                    opening_hours=row[6], price_cny=row[7], verified_at=_VERIFIED)


@router.get("/places", response_model=list[PlaceOut], summary="搜索全国目的地与地点")
def places(city: str = Query(min_length=1), keyword: str | None = Query(default=None)):
    rows = [row for row in _PLACES if row[2] == city]
    if keyword:
        word = keyword.strip().lower()
        rows = [row for row in rows if word in row[1].lower() or word in (row[3] or "").lower()]
    return [_place(row) for row in rows[:50]]


@router.get("/knowledge/search", response_model=list[KnowledgeHitOut], summary="检索已授权的旅游资料")
def knowledge(city: str = Query(min_length=1), query: str = Query(min_length=1)):
    theme_rows = [theme for theme in themes.list_themes(city=city)]
    word = query.strip().lower()
    hits = []
    for row in theme_rows:
        detail = themes.get_theme(row["code"])
        for fact in detail["facts"]:
            haystack = " ".join([fact["title"], fact["place_name"], fact["value"]]).lower()
            if word in haystack:
                hits.append(KnowledgeHitOut(
                    title=f"{fact['place_name']} · {fact['title']}",
                    excerpt=fact["value"],
                    source_url=f"https://traveltrace.demo/sources/{fact['id']}",
                    verified_at=fact["observed_at"] if fact["verified"] else None,
                ))
    return hits[:20]
