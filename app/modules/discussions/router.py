from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import current_user
from app.db.models import Message, Room, User
from app.db.session import get_session
from app.modules.discussions.schemas import CreateMessage, MessagePage, MessageResponse
from app.modules.rooms.service import ensure_writable, require_member

router = APIRouter(tags=["讨论与导入"])


@router.post("/rooms/{room_id}/messages", response_model=MessageResponse, status_code=201, summary="提交房间讨论消息")
def send(room_id: UUID, body: CreateMessage, user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    ensure_writable(session.get(Room, room_id))
    # Serialize inserts within a room so a later committed sequence cannot
    # advance the polling cursor past an earlier, still uncommitted message.
    session.scalar(select(Room).where(Room.id == room_id).with_for_update())
    message = Message(room_id=room_id, author_member_id=member.id, content=body.content)
    session.add(message)
    session.commit()
    return message


@router.get("/rooms/{room_id}/messages", response_model=MessagePage, summary="分页查看讨论消息")
def messages(room_id: UUID, after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
             user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    rows = session.scalars(select(Message).where(Message.room_id == room_id, Message.sequence > after)
                           .order_by(Message.sequence).limit(limit + 1)).all()
    items = rows[:limit]
    return MessagePage(items=[MessageResponse.model_validate(x) for x in items],
                       next_cursor=items[-1].sequence if items else after, has_more=len(rows) > limit)