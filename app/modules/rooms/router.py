from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import Member, Room, User
from app.db.session import get_session
from app.modules.rooms.schemas import CreateInvitation, CreateRoom, InvitationResponse, JoinRoom, MemberResponse, RoomResponse
from app.modules.rooms.service import create_invitation, join_room, require_member

router = APIRouter(tags=["旅行房间"])


@router.post("/rooms", response_model=RoomResponse, status_code=201, summary="创建旅行房间")
def create(body: CreateRoom, user: User = Depends(current_user), session: Session = Depends(get_session)):
    room = Room(**body.model_dump(), owner_id=user.id)
    session.add(room)
    session.flush()
    session.add(Member(room_id=room.id, user_id=user.id, display_name=user.display_name, role="owner"))
    session.commit()
    return room


@router.get("/rooms", response_model=list[RoomResponse], summary="查看我的房间")
def list_rooms(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
               user: User = Depends(current_user), session: Session = Depends(get_session)):
    return session.scalars(select(Room).join(Member, Member.room_id == Room.id)
                           .where(Member.user_id == user.id, Member.status == "active")
                           .order_by(Room.created_at.desc(), Room.id).limit(limit).offset(offset)).all()


@router.post("/rooms/join", response_model=MemberResponse, status_code=201, summary="通过邀请码加入房间")
def join(body: JoinRoom, user: User = Depends(current_user), session: Session = Depends(get_session)):
    return join_room(session, user, body.invite_code, body.display_name)


@router.get("/rooms/{room_id}", response_model=RoomResponse, summary="查看房间详情")
def detail(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    return session.get(Room, room_id)


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
