from uuid import UUID

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import Invitation, Member, PlanVersion, Room, User, utcnow
from app.db.session import get_session
from app.modules.rooms.schemas import (
    CreateInvitation, CreateRoom, InvitationResponse, JoinRoom, LeftRoom, MemberResponse, RevokedCount,
    RoomResponse, TravelWindowIn, TravelWindowOut,
)
from app.modules.rooms.service import (
    check_room_version, create_invitation, ensure_writable, join_room, lock_room, present_room,
    require_member, require_owner, validate_tags, validate_theme_for_destination,
)

router = APIRouter(tags=["旅行房间"])


@router.post("/rooms", response_model=RoomResponse, status_code=201, summary="创建旅行房间")
def create(body: CreateRoom, user: User = Depends(current_user), session: Session = Depends(get_session)):
    validate_theme_for_destination(body.theme_code, body.destination)
    validate_tags(body.interest_tag_codes)
    room = Room(name=body.name, destination=body.destination, start_date=body.start_date,
                end_date=body.end_date, theme_code=body.theme_code,
                seed_interest_tag_codes=body.interest_tag_codes or None, owner_id=user.id)
    session.add(room)
    session.flush()
    session.add(Member(room_id=room.id, user_id=user.id, display_name=user.display_name, role="owner"))
    session.commit()
    return present_room(session, room)


@router.get("/rooms", response_model=list[RoomResponse], summary="查看我的房间")
def list_rooms(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
               user: User = Depends(current_user), session: Session = Depends(get_session)):
    rooms = session.scalars(select(Room).join(Member, Member.room_id == Room.id)
                            .where(Member.user_id == user.id, Member.status == "active")
                            .order_by(Room.created_at.desc(), Room.id).limit(limit).offset(offset)).all()
    return [present_room(session, room) for room in rooms]


@router.post("/rooms/join", response_model=MemberResponse, status_code=201, summary="通过邀请码加入房间")
def join(body: JoinRoom, user: User = Depends(current_user), session: Session = Depends(get_session)):
    return join_room(session, user, body.invite_code, body.display_name)


@router.get("/rooms/{room_id}", response_model=RoomResponse, summary="查看房间详情")
def detail(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    return present_room(session, session.get(Room, room_id))


@router.get("/rooms/{room_id}/members", response_model=list[MemberResponse], summary="查看房间成员")
def members(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    return session.scalars(select(Member).where(Member.room_id == room_id, Member.status == "active")
                           .order_by(Member.joined_at, Member.id)).all()


@router.post("/rooms/{room_id}/invitations", response_model=InvitationResponse, status_code=201, summary="创建房间邀请码")
def invitation(room_id: UUID, body: CreateInvitation, user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    if member.role != "owner":
        raise ApiError(403, "OWNER_REQUIRED", "仅房主可以生成邀请码")
    room = session.get(Room, room_id)
    if room.status != "collecting":
        raise ApiError(409, "ROOM_NOT_JOINABLE", "当前房间状态不允许邀请")
    return create_invitation(session, room, body.expires_in_hours)

@router.delete("/rooms/{room_id}/invitations", response_model=RevokedCount, summary="撤销房间未过期邀请")
def revoke_invitations(room_id: UUID, user: User = Depends(current_user),
                       session: Session = Depends(get_session)):
    room, _ = require_owner(session, room_id, user.id)
    result = session.execute(delete(Invitation).where(Invitation.room_id == room_id,
                                                      Invitation.expires_at > utcnow()))
    session.commit()
    revoked = max(result.rowcount or 0, 0)
    return RevokedCount(revoked_count=revoked)


@router.put("/rooms/{room_id}/schedule", response_model=TravelWindowOut, summary="设置旅行起止时间")
def set_schedule(room_id: UUID, body: TravelWindowIn, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    room, _ = require_owner(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    try:
        tz = ZoneInfo(body.time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ApiError(422, "INVALID_TIME_ZONE", "时区必须是 IANA 时区") from None
    starts, ends = body.starts_at, body.ends_at
    if starts.tzinfo is None or ends.tzinfo is None:
        raise ApiError(422, "INVALID_WINDOW", "起止时间必须带时区")
    if ends <= starts:
        raise ApiError(422, "INVALID_WINDOW", "结束时间必须晚于开始时间")
    local_start = starts.astimezone(tz)
    local_end = ends.astimezone(tz)
    if local_start.date() < room.start_date or local_end.date() > room.end_date:
        raise ApiError(422, "OUT_OF_ROOM_DATES", "行程时间必须落在房间日期范围内")
    published = session.scalar(select(PlanVersion).where(PlanVersion.room_id == room.id,
                                                         PlanVersion.status == "published"))
    if published is not None:
        for item in published.activities or []:
            from app.modules.plans.service import parse_dt
            item_start = parse_dt(item.get("starts_at"))
            item_end = parse_dt(item.get("ends_at"))
            if item_start and (item_start < starts or item_end > ends):
                raise ApiError(409, "COMMITMENT_CONFLICT", "新时间窗会影响已生效的固定安排")
    room.window_starts_at = starts
    room.window_ends_at = ends
    room.time_zone = body.time_zone
    room.start_date = local_start.date()
    room.end_date = local_end.date()
    room.version += 1
    room.updated_at = utcnow()
    session.commit()
    return TravelWindowOut(starts_at=starts, ends_at=ends, time_zone=body.time_zone,
                           room_version=room.version)


@router.delete("/rooms/{room_id}/members/me", response_model=LeftRoom, summary="主动退出旅行房间")
def leave_room(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    if member.role == "owner":
        raise ApiError(409, "OWNER_CANNOT_LEAVE", "房主不能退出自己的房间")
    published = session.scalar(select(PlanVersion).where(PlanVersion.room_id == room.id,
                                                         PlanVersion.status == "published"))
    if published is not None:
        raise ApiError(409, "ACTIVE_COMMITMENT", "仍存在生效行程，请先通过重规划处理既有承诺")
    member.status = "left"
    room.version += 1
    room.updated_at = utcnow()
    session.commit()
    return LeftRoom(left=True)