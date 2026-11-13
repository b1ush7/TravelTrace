from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import PlanVersion, Room, User, utcnow
from app.db.session import get_session
from app.modules.rooms.schemas import RoomResponse
from app.modules.rooms.service import (
    check_room_version, ensure_writable, lock_room, present_room, require_owner,
    validate_theme_for_destination,
)
from app.modules.themes import catalog
from app.modules.themes.schemas import SetRoomTheme, ThemeDetailOut, ThemeOut, ThemePackOut

router = APIRouter(tags=["主题游"])


@router.get("/themes", response_model=list[ThemeOut], summary="获取主题列表")
def themes(domain: str | None = Query(default=None), city: str | None = Query(default=None)):
    return catalog.list_themes(domain=domain, city=city)


@router.get("/themes/{theme_code}", response_model=ThemeDetailOut, summary="查看主题详情")
def theme(theme_code: str):
    detail = catalog.get_theme(theme_code)
    if detail is None:
        raise ApiError(404, "THEME_NOT_FOUND", "主题不存在")
    return detail


@router.get("/themes/{theme_code}/packs", response_model=list[ThemePackOut], summary="查看主题行程包")
def packs(theme_code: str):
    result = catalog.get_packs(theme_code)
    if result is None:
        raise ApiError(404, "THEME_NOT_FOUND", "主题不存在")
    return result


@router.put("/rooms/{room_id}/theme", response_model=RoomResponse, summary="设置房间主题")
def set_room_theme(room_id: UUID, body: SetRoomTheme, user: User = Depends(current_user),
                   session: Session = Depends(get_session)):
    room, _ = require_owner(session, room_id, user.id)
    room = lock_room(session, room.id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    if body.theme_code == room.theme_code:
        return present_room(session, room)
    if body.theme_code is not None:
        validate_theme_for_destination(body.theme_code, room.destination)
        published = session.scalar(select(PlanVersion.id).where(
            PlanVersion.room_id == room.id, PlanVersion.status == "published"))
        if published is not None:
            raise ApiError(409, "THEME_LOCKED", "已有生效版本，请通过 replan-jobs 生成主题变更提案")
    room.theme_code = body.theme_code
    room.version += 1
    room.updated_at = utcnow()
    session.commit()
    return present_room(session, room)
