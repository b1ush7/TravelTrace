import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import Room, User
from app.db.session import get_session
from app.modules.interests.catalog import DOMAINS
from app.modules.interests.schemas import (
    InterestStatsOut, InterestTagOut, InterestsUpdate, MemberInterestProfileOut, RoomInterestOverviewOut,
)
from app.modules.interests.service import profile, replace_interests, room_overview, stats, tags_payload
from app.modules.rooms.service import require_member

router = APIRouter(tags=["兴趣标签"])


@router.get("/interests/tags", response_model=list[InterestTagOut], summary="获取兴趣标签字典")
def tags(request: Request, response: Response, domain: str | None = Query(default=None)):
    if domain is not None and domain not in DOMAINS:
        raise ApiError(400, "INVALID_DOMAIN", "未知的兴趣域")
    payload = [item.model_dump(mode="json") for item in tags_payload(domain)]
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    etag = 'W/"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "public, max-age=86400"})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=86400"
    return payload


@router.get("/me/interests", response_model=MemberInterestProfileOut, summary="查看本人兴趣标签")
def my_interests(user: User = Depends(current_user), session: Session = Depends(get_session)):
    return profile(session, user)


@router.put("/me/interests", response_model=MemberInterestProfileOut, summary="全量设置本人兴趣标签")
def set_my_interests(body: InterestsUpdate, user: User = Depends(current_user),
                     session: Session = Depends(get_session)):
    return replace_interests(session, user, body)


@router.get("/me/interests/stats", response_model=InterestStatsOut, summary="查看本人兴趣统计")
def my_stats(user: User = Depends(current_user), session: Session = Depends(get_session)):
    return stats(session, user)


@router.get("/rooms/{room_id}/interests", response_model=RoomInterestOverviewOut,
            summary="查看房间兴趣聚合")
def room_interests(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    room = session.get(Room, room_id)
    return room_overview(session, room)
