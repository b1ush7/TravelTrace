from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import Conflict, Decision, Member, Proposal, Room, User, utcnow
from app.db.session import get_session
from app.modules.proposals.schemas import (
    ConcludeIn, CreateProposalIn, DecisionOut, ProposalOut, VoteIn, VoteResult,
)
from app.modules.rooms.service import check_room_version, ensure_writable, lock_room, require_member, require_owner

router = APIRouter(tags=["协商与投票"])


def _proposal(session: Session, room_id: UUID, proposal_id: UUID) -> Proposal:
    row = session.get(Proposal, proposal_id)
    if row is None or row.room_id != room_id:
        raise ApiError(404, "PROPOSAL_NOT_FOUND", "提案不存在")
    return row


def proposal_out(row: Proposal) -> ProposalOut:
    return ProposalOut(
        id=row.id, conflict_id=row.conflict_id, title=row.title, options=row.options or [],
        status=row.status, created_at=row.created_at, votes=row.votes or [],
        pending_member_ids=[UUID(str(item)) for item in (row.pending_member_ids or [])],
        affected_hard_constraint_member_ids=[UUID(str(item)) for item in (row.affected_hard_constraint_member_ids or [])],
        deadline=row.deadline, version=row.version,
        eligible_member_ids=[UUID(str(item)) for item in (row.eligible_member_ids or [])],
        decision_id=row.decision_id, outcome_rule="absolute_majority",
    )


def decision_out(row: Decision) -> DecisionOut:
    return DecisionOut(id=row.id, proposal_id=row.proposal_id, selected_option_id=row.selected_option_id,
                       room_version=row.room_version, effect=row.effect,
                       pending_member_ids=[UUID(str(item)) for item in (row.pending_member_ids or [])],
                       created_at=row.created_at)


@router.post("/rooms/{room_id}/proposals", response_model=ProposalOut, status_code=201,
             summary="针对分歧创建协商提案")
def create_proposal(room_id: UUID, body: CreateProposalIn, user: User = Depends(current_user),
                    session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    affected = []
    if body.conflict_id is not None:
        conflict = session.get(Conflict, body.conflict_id)
        if conflict is None or conflict.room_id != room_id:
            raise ApiError(404, "CONFLICT_NOT_FOUND", "冲突不存在")
        affected = [str(item) for item in (conflict.key_member_ids or [])]
    members = session.scalars(select(Member).where(Member.room_id == room_id,
                                                   Member.status == "active")).all()
    eligible = [str(item.id) for item in members]
    options = [{"id": str(uuid4()), "label": option.label} for option in body.options]
    proposal = Proposal(room_id=room_id, conflict_id=body.conflict_id, created_by_member_id=member.id,
                        title=body.title, options=options, status="open", votes=[],
                        pending_member_ids=list(eligible),
                        affected_hard_constraint_member_ids=affected,
                        eligible_member_ids=eligible, deadline=body.deadline, version=1,
                        outcome_rule="absolute_majority")
    session.add(proposal)
    room.version += 1
    proposal.input_room_version = room.version
    room.updated_at = utcnow()
    session.commit()
    return proposal_out(proposal)


@router.get("/rooms/{room_id}/proposals", response_model=list[ProposalOut], summary="查看协商提案")
def list_proposals(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    rows = session.scalars(select(Proposal).where(Proposal.room_id == room_id)
                           .order_by(Proposal.created_at.desc(), Proposal.id)).all()
    return [proposal_out(row) for row in rows]


@router.get("/rooms/{room_id}/proposals/{proposal_id}", response_model=ProposalOut,
            summary="查看提案及投票结果")
def get_proposal(room_id: UUID, proposal_id: UUID, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    return proposal_out(_proposal(session, room_id, proposal_id))


@router.put("/rooms/{room_id}/proposals/{proposal_id}/vote", response_model=VoteResult,
            summary="提交或修改本人投票")
def vote(room_id: UUID, proposal_id: UUID, body: VoteIn, user: User = Depends(current_user),
         session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    proposal = _proposal(session, room_id, proposal_id)
    if proposal.status != "open":
        raise ApiError(409, "PROPOSAL_CLOSED", "提案已关闭")
    if proposal.version != body.expected_proposal_version:
        raise ApiError(409, "VERSION_CONFLICT", "提案版本已变化")
    if str(member.id) not in [str(item) for item in (proposal.eligible_member_ids or [])]:
        raise ApiError(403, "NOT_ELIGIBLE", "你不具备本提案投票资格")
    if str(body.option_id) not in [option["id"] for option in (proposal.options or [])]:
        raise ApiError(422, "OPTION_UNKNOWN", "选项不存在")
    votes = [dict(item) for item in (proposal.votes or []) if str(item.get("member_id")) != str(member.id)]
    votes.append({"member_id": str(member.id), "option_id": str(body.option_id)})
    proposal.votes = votes
    flag_modified(proposal, "votes")
    voted = {str(item["member_id"]) for item in votes}
    proposal.pending_member_ids = [item for item in (proposal.eligible_member_ids or []) if item not in voted]
    proposal.version += 1
    session.commit()
    return VoteResult(proposal_id=proposal.id, option_id=body.option_id, member_id=member.id)


@router.post("/rooms/{room_id}/proposals/{proposal_id}/conclusion", response_model=DecisionOut,
             summary="结算提案并形成决定")
def conclude(room_id: UUID, proposal_id: UUID, body: ConcludeIn, user: User = Depends(current_user),
             session: Session = Depends(get_session)):
    room, _ = require_owner(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    proposal = _proposal(session, room_id, proposal_id)
    existing = session.scalar(select(Decision).where(Decision.proposal_id == proposal.id))
    if proposal.status == "decided" and existing is not None:
        return decision_out(existing)
    check_room_version(room, body.expected_room_version)
    if proposal.status == "closed_no_consensus":
        raise ApiError(409, "NO_CONSENSUS", "提案未达成共识")
    if proposal.version != body.expected_proposal_version:
        raise ApiError(409, "VERSION_CONFLICT", "提案版本已变化")
    if proposal.input_room_version != room.version:
        proposal.status = "stale"
        session.commit()
        raise ApiError(409, "STALE_PROPOSAL", "房间版本已变化，提案失效")
    eligible = [str(item) for item in (proposal.eligible_member_ids or [])]
    votes = proposal.votes or []
    deadline = proposal.deadline
    if deadline is not None:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
    if len(votes) < len(eligible) and (deadline is None or deadline > utcnow()):
        raise ApiError(409, "VOTING_INCOMPLETE", "仍有成员未投票")
    tally: dict[str, int] = {}
    for item in votes:
        option_id = str(item.get("option_id"))
        tally[option_id] = tally.get(option_id, 0) + 1
    winner = next((option_id for option_id, count in tally.items() if count * 2 > len(eligible)), None)
    if winner is None:
        proposal.status = "closed_no_consensus"
        session.commit()
        raise ApiError(409, "NO_CONSENSUS", "没有选项获得过半支持")
    affected = [str(item) for item in (proposal.affected_hard_constraint_member_ids or [])]
    effect = "requires_personal_confirmation" if affected else "preference_recorded"
    room.version += 1
    room.updated_at = utcnow()
    decision = Decision(room_id=room_id, proposal_id=proposal.id, selected_option_id=UUID(winner),
                        room_version=room.version, effect=effect, pending_member_ids=affected)
    session.add(decision)
    session.flush()
    proposal.status = "decided"
    proposal.decision_id = decision.id
    session.commit()
    return decision_out(decision)


@router.get("/rooms/{room_id}/decisions", response_model=list[DecisionOut], summary="查看已形成的协商决定")
def list_decisions(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    rows = session.scalars(select(Decision).where(Decision.room_id == room_id)
                           .order_by(Decision.created_at.desc(), Decision.id)).all()
    return [decision_out(row) for row in rows]