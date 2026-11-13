import hashlib
import secrets
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import ShareLink, User, utcnow
from app.db.session import get_session
from app.modules.plans.service import current_published, parse_dt
from app.modules.rooms.service import require_member, require_owner
from app.modules.sharing.schemas import (
    CreateRoomHint, ShareInput, ShareLinkOut, SharedActivity, SharedPlanOut, SharedTheme,
)
from app.modules.themes import catalog as themes

router = APIRouter(tags=["行程分享"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/rooms/{room_id}/share-links", response_model=ShareLinkOut, status_code=201,
             summary="创建脱敏行程分享链接")
def create_share(room_id: UUID, body: ShareInput, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    room, member = require_owner(session, room_id, user.id)
    version = current_published(session, room_id)
    if version is None:
        raise ApiError(409, "NO_PUBLISHED_VERSION", "还没有可分享的生效版本")
    expires = body.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= utcnow():
        raise ApiError(422, "INVALID_EXPIRY", "分享有效期必须晚于当前时间")
    token = secrets.token_urlsafe(24)
    row = ShareLink(room_id=room_id, created_by_member_id=member.id, token_hash=_hash(token),
                    expires_at=expires)
    session.add(row)
    session.commit()
    return ShareLinkOut(id=row.id, url=f"https://traveltrace.demo/s/{token}", expires_at=row.expires_at)


@router.delete("/rooms/{room_id}/share-links/{share_id}", status_code=204, summary="撤销行程分享链接")
def revoke_share(room_id: UUID, share_id: UUID, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    row = session.get(ShareLink, share_id)
    if row is None or row.room_id != room_id:
        raise ApiError(404, "SHARE_NOT_FOUND", "分享链接不存在")
    if member.role != "owner" and row.created_by_member_id != member.id:
        raise ApiError(403, "NOT_SHARE_OWNER", "只有创建人或房主可以撤销")
    row.revoked_at = utcnow()
    session.commit()
    return Response(status_code=204)


@router.get("/shared-plans/{share_token}", response_model=SharedPlanOut, summary="读取脱敏的当前计划")
def shared_plan(share_token: str, session: Session = Depends(get_session)):
    row = session.scalar(select(ShareLink).where(ShareLink.token_hash == _hash(share_token)))
    if row is None or row.revoked_at is not None:
        raise ApiError(404, "SHARE_NOT_FOUND", "分享链接无效或已撤销")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= utcnow():
        raise ApiError(404, "SHARE_NOT_FOUND", "分享链接无效或已撤销")
    version = current_published(session, row.room_id)
    if version is None:
        raise ApiError(404, "NO_PUBLISHED_VERSION", "还没有可分享的生效版本")
    from app.db.models import Room
    room = session.get(Room, row.room_id)
    items = []
    for item in version.activities or []:
        start, end = parse_dt(item.get("starts_at")), parse_dt(item.get("ends_at"))
        if start is None or end is None:
            continue
        items.append(SharedActivity(title=item.get("title", ""), place_name=item.get("place_name", ""),
                                    starts_at=start, ends_at=end, kind=item.get("kind", "activity")))
    days = (room.end_date - room.start_date).days + 1
    theme = None
    if room.theme_code and themes.exists(room.theme_code):
        theme = SharedTheme(code=room.theme_code, name=themes.name(room.theme_code),
                            badge=themes.badge(room.theme_code))
    return SharedPlanOut(
        destination=room.destination,
        updated_at=version.published_at or version.updated_at,
        activities=items,
        theme=theme,
        create_room_hint=CreateRoomHint(destination=room.destination, theme_code=room.theme_code, days=days),
    )
