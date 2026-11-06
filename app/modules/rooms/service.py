import hashlib
import secrets
from datetime import timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import Invitation, Member, Room, User, utcnow


def require_member(session: Session, room_id: UUID, user_id: UUID) -> Member:
    member = session.scalar(select(Member).where(Member.room_id == room_id, Member.user_id == user_id,
                                                 Member.status == "active"))
    if member is None:
        raise ApiError(403, "NOT_ROOM_MEMBER", "仅房间成员可访问")
    return member


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
