import hashlib
import secrets
from datetime import timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import Invitation, Member, Room, User, utcnow
from app.modules.interests.catalog import TAGS_BY_CODE
from app.modules.interests.service import apply_summary
from app.modules.rooms.schemas import RoomResponse
from app.modules.themes import catalog as themes


def require_member(session: Session, room_id: UUID, user_id: UUID) -> Member:
    member = session.scalar(select(Member).where(Member.room_id == room_id, Member.user_id == user_id,
                                                 Member.status == "active"))
    if member is None:
        raise ApiError(403, "NOT_MEMBER", "仅房间成员可访问")
    return member


def require_owner(session: Session, room_id: UUID, user_id: UUID) -> tuple[Room, Member]:
    member = require_member(session, room_id, user_id)
    room = session.get(Room, room_id)
    if member.role != "owner":
        raise ApiError(403, "OWNER_REQUIRED", "仅房主可以操作")
    return room, member


def ensure_writable(room: Room) -> None:
    if room.status == "archived":
        raise ApiError(409, "ROOM_ARCHIVED", "房间已归档，只能查看")


def check_room_version(room: Room, expected: int) -> None:
    if room.version != expected:
        raise ApiError(409, "VERSION_CONFLICT", "房间版本已变化，请刷新后重试")


def lock_room(session: Session, room_id: UUID) -> Room:
    room = session.scalar(select(Room).where(Room.id == room_id).with_for_update())
    if room is None:
        raise ApiError(404, "ROOM_NOT_FOUND", "房间不存在")
    return room


def present_room(session: Session, room: Room) -> RoomResponse:
    apply_summary(session, room)
    return RoomResponse.model_validate(room)


def validate_theme_for_destination(theme_code: str | None, destination: str) -> None:
    if theme_code is None:
        return
    if not themes.exists(theme_code):
        raise ApiError(422, "THEME_NOT_FOUND", "主题不存在")
    if themes.city_scope(theme_code) != destination:
        raise ApiError(422, "THEME_CITY_MISMATCH", "主题与目的地不匹配")


def validate_tags(codes: list[str]) -> None:
    unknown = [code for code in codes if code not in TAGS_BY_CODE]
    if unknown:
        raise ApiError(422, "TAG_UNKNOWN", f"未知标签：{unknown[0]}")


def create_invitation(session: Session, room: Room, hours: int):
    code = secrets.token_urlsafe(18)
    expires = utcnow() + timedelta(hours=hours)
    session.add(Invitation(room_id=room.id, code_hash=hashlib.sha256(code.encode()).hexdigest(), expires_at=expires))
    session.commit()
    return {"invite_code": code, "expires_at": expires}


def join_room(session: Session, user: User, code: str, display_name: str | None):
    invite = session.scalar(select(Invitation).where(Invitation.code_hash == hashlib.sha256(code.encode()).hexdigest()))
    if invite is None:
        raise ApiError(400, "INVALID_INVITATION", "邀请码无效或已过期")
    # Serialize membership changes to enforce capacity and prevent duplicate joins.
    room = session.scalar(select(Room).where(Room.id == invite.room_id).with_for_update())
    expires = invite.expires_at
    if expires.tzinfo is None:  # SQLite unit tests return naive datetimes.
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= utcnow() or room is None:
        raise ApiError(400, "INVALID_INVITATION", "邀请码无效或已过期")
    existing = session.scalar(select(Member).where(Member.room_id == room.id, Member.user_id == user.id))
    if existing:
        return existing
    if room.status != "collecting":
        raise ApiError(409, "ROOM_NOT_JOINABLE", "当前房间状态不允许加入")
    count = session.scalar(select(func.count()).select_from(Member).where(Member.room_id == room.id, Member.status == "active"))
    if count >= 6:
        raise ApiError(409, "ROOM_FULL", "房间最多容纳六人")
    member = Member(room_id=room.id, user_id=user.id, display_name=display_name or user.display_name, role="member")
    session.add(member)
    room.version += 1
    session.commit()
    return member
