from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import Claim, Member, Participation, Room, User, utcnow
from app.db.session import get_session
from app.modules.claims.schemas import (
    ClaimDecision, ClaimOut, CreateClaim, ParticipationInput, ParticipationOut, UpdateClaim,
)
from app.modules.claims.service import claim_out, claim_value_dict
from app.modules.rooms.service import check_room_version, ensure_writable, lock_room, require_member

router = APIRouter(tags=["成员需求"])


def _claim_in_room(session: Session, room_id: UUID, claim_id: UUID) -> Claim:
    claim = session.get(Claim, claim_id)
    if claim is None or claim.room_id != room_id:
        raise ApiError(404, "CLAIM_NOT_FOUND", "需求不存在")
    return claim


@router.get("/rooms/{room_id}/claims", response_model=list[ClaimOut], summary="查看成员需求与确认状态")
def list_claims(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    rows = session.scalars(select(Claim).where(Claim.room_id == room_id)
                           .order_by(Claim.created_at, Claim.id)).all()
    return [claim_out(row) for row in rows]


@router.post("/rooms/{room_id}/claims", response_model=ClaimOut, status_code=201, summary="提交本人需求")
def create_claim(room_id: UUID, body: CreateClaim, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    claim = Claim(room_id=room_id, subject_member_id=member.id, speaker_member_id=member.id,
                  field=body.field, value=claim_value_dict(body.value), condition=body.condition,
                  polarity=body.polarity, strength=body.strength, status="pending", version=1)
    session.add(claim)
    room.version += 1
    room.updated_at = utcnow()
    session.commit()
    return claim_out(claim)


@router.patch("/rooms/{room_id}/claims/{claim_id}", response_model=ClaimOut, summary="修改本人的需求并重新确认")
def update_claim(room_id: UUID, claim_id: UUID, body: UpdateClaim, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    claim = _claim_in_room(session, room_id, claim_id)
    if claim.subject_member_id != member.id:
        raise ApiError(403, "NOT_CLAIM_OWNER", "只能修改本人的需求")
    if claim.version != body.expected_version:
        raise ApiError(409, "VERSION_CONFLICT", "需求版本已变化，请刷新后重试")
    fields = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    if "value" in fields:
        if fields["value"] is None:
            raise ApiError(422, "VALIDATION_ERROR", "value 不能为空")
        claim.value = claim_value_dict(body.value)
    if "condition" in fields:
        claim.condition = fields["condition"]
    if "polarity" in fields:
        claim.polarity = fields["polarity"]
    if "strength" in fields:
        claim.strength = fields["strength"]
    claim.status = "pending"
    claim.version += 1
    room.version += 1
    room.updated_at = utcnow()
    session.commit()
    return claim_out(claim)


@router.post("/rooms/{room_id}/claims/{claim_id}/decision", response_model=ClaimOut,
             summary="确认、驳回或撤回本人需求")
def decide_claim(room_id: UUID, claim_id: UUID, body: ClaimDecision, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    claim = _claim_in_room(session, room_id, claim_id)
    if claim.subject_member_id != member.id:
        raise ApiError(403, "NOT_CLAIM_OWNER", "只能处理本人的需求")
    if claim.version != body.expected_version:
        raise ApiError(409, "VERSION_CONFLICT", "需求版本已变化，请刷新后重试")
    claim.status = {"confirm": "confirmed", "reject": "rejected", "withdraw": "withdrawn"}[body.decision]
    claim.version += 1
    room.version += 1
    room.updated_at = utcnow()
    session.commit()
    return claim_out(claim)


@router.put("/rooms/{room_id}/members/me/participation", response_model=ParticipationOut,
            summary="设置本人参与区间")
def set_participation(room_id: UUID, body: ParticipationInput, user: User = Depends(current_user),
                      session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    if body.leaves_at <= body.joins_at:
        raise ApiError(422, "INVALID_WINDOW", "离开时间必须晚于加入时间")
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    row = session.scalar(select(Participation).where(Participation.room_id == room_id,
                                                     Participation.member_id == member.id))
    if row is None:
        row = Participation(room_id=room_id, member_id=member.id, joins_at=body.joins_at,
                            leaves_at=body.leaves_at, allow_solo=body.allow_solo, version=1)
        session.add(row)
    else:
        row.joins_at = body.joins_at
        row.leaves_at = body.leaves_at
        row.allow_solo = body.allow_solo
        row.version += 1
    room.version += 1
    room.updated_at = utcnow()
    session.commit()
    return ParticipationOut(member_id=member.id, joins_at=row.joins_at, leaves_at=row.leaves_at,
                            allow_solo=row.allow_solo, room_version=room.version)
