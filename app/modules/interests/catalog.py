from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tag:
    code: str
    name: str
    domain: str
    sort: int


# 11 domains, 60 tags. The dictionary is product content, not user data; it is
# versioned with the code and cached by ETag for 24 hours.
DOMAINS = (
    "nature", "culture", "food", "play", "shopping", "nightlife",
    "red", "outdoor", "photo", "show", "family",
)

_TAGS: tuple[tuple[str, str, str], ...] = (
    # nature
    ("mountain", "山野", "nature"), ("lake", "湖泊", "nature"), ("beach", "海滨", "nature"),
    ("forest", "森林", "nature"), ("grassland", "草原", "nature"), ("desert", "沙漠", "nature"),
    ("island", "海岛", "nature"), ("waterfall", "瀑布", "nature"),
    # culture
    ("history", "历史人文", "culture"), ("museum", "博物馆", "culture"),
    ("ancient_town", "古镇", "culture"), ("temple", "寺庙", "culture"),
    ("architecture", "建筑", "culture"), ("folk", "民俗", "culture"),
    ("red_history", "红色历史", "culture"), ("intangible_heritage", "非遗", "culture"),
    # food
    ("local_food", "地方菜", "food"), ("street_food", "小吃街", "food"),
    ("fine_dining", "精致餐饮", "food"), ("dessert", "甜品", "food"),
    ("coffee", "咖啡", "food"), ("night_market", "夜市", "food"), ("hotpot", "火锅", "food"),
    # play
    ("theme_park", "主题乐园", "play"), ("amusement", "游乐园", "play"),
    ("water_park", "水上乐园", "play"), ("escape_room", "密室", "play"),
    ("ktv", "KTV", "play"), ("board_game", "桌游", "play"),
    # shopping
    ("mall", "商场", "shopping"), ("market", "市集", "shopping"),
    ("boutique", "买手店", "shopping"), ("duty_free", "免税店", "shopping"),
    # nightlife
    ("bar", "酒吧", "nightlife"), ("livehouse", "Livehouse", "nightlife"),
    ("club", "夜店", "nightlife"), ("night_view", "夜景", "nightlife"),
    # red
    ("revolutionary_site", "革命旧址", "red"), ("memorial_hall", "纪念馆", "red"),
    ("party_history", "党史展陈", "red"), ("red_village", "红色村落", "red"),
    # outdoor
    ("hiking", "徒步", "outdoor"), ("camping", "露营", "outdoor"),
    ("cycling", "骑行", "outdoor"), ("rafting", "漂流", "outdoor"),
    ("climbing", "攀岩", "outdoor"), ("stargazing", "观星", "outdoor"),
    # photo
    ("city_walk", "城市漫步", "photo"), ("sunrise", "日出", "photo"),
    ("sunset", "日落", "photo"), ("street_photo", "街拍", "photo"),
    ("portrait", "人像摄影", "photo"),
    # show
    ("concert", "演唱会", "show"), ("festival", "音乐节", "show"),
    ("theater", "戏剧", "show"), ("exhibition", "展览", "show"),
    # family
    ("zoo", "动物园", "family"), ("aquarium", "海洋馆", "family"),
    ("science_museum", "科技馆", "family"), ("playground", "亲子乐园", "family"),
)

TAGS: tuple[Tag, ...] = tuple(
    Tag(code=code, name=name, domain=domain, sort=index + 1)
    for index, (code, name, domain) in enumerate(_TAGS)
)
TAGS_BY_CODE = {tag.code: tag for tag in TAGS}


def as_dict(tag: Tag) -> dict:
    return {
        "code": tag.code,
        "name": tag.name,
        "domain": tag.domain,
        "parent_code": None,
        "icon": None,
        "sort": tag.sort,
    }
