from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import current_user
from app.db.models import Deal, Room, User
from app.db.session import get_session
from app.modules.deals.schemas import CreateDeal, DealOut
from app.modules.rooms.service import ensure_writable, require_member

router = APIRouter(tags=["团购协作"])


@router.get("/rooms/{room_id}/deals", response_model=list[DealOut], summary="查看房间团购")
def list_deals(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    return session.scalars(select(Deal).where(Deal.room_id == room_id)
                           .order_by(Deal.created_at.desc(), Deal.id)).all()


@router.post("/rooms/{room_id}/deals", response_model=DealOut, status_code=201, summary="提交用户提供的团购")
def create_deal(room_id: UUID, body: CreateDeal, user: User = Depends(current_user),
                session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    ensure_writable(session.get(Room, room_id))
    deal = Deal(room_id=room_id, created_by_member_id=member.id, title=body.title,
                place_name=body.place_name, price_cny=body.price_cny, people_count=body.people_count,
                valid_until=body.valid_until, url=body.url, source="user",
                verification_status="unverified", confirmed_by=[])
    session.add(deal)
    session.commit()
    return deal