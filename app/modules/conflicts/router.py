from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import Conflict, ConflictAction, ConflictOption, Room, User
from app.db.session import get_session
from app.modules.conflicts.schemas import (
    ConflictOut, ConflictRefreshOut, ConflictRefreshRequest, ResolutionsOut, ResolutionOut, ResolveRequest,
    ResolveResult,
)
from app.modules.conflicts.service import (
    apply_relax, conflict_out, create_pending_version, generate_options, issues_from_conflicts,
    refresh_conflicts, resolve_conflicts_for_read,
)
from app.modules.rooms.service import check_room_version, ensure_writable, lock_room, require_member

router = APIRouter(tags=["协商与投票"])


def _conflict(session: Session, room_id: UUID, conflict_id: UUID) -> Conflict:
    conflict = session.get(Conflict, conflict_id)
    if conflict is None or conflict.room_id != room_id:
        raise ApiError(404, "CONFLICT_NOT_FOUND", "冲突不存在")
    return conflict


@router.get("/rooms/{room_id}/conflicts", response_model=list[ConflictOut], summary="查看已识别的条件冲突")
def list_conflicts(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    room = session.get(Room, room_id)
    rows = resolve_conflicts_for_read(session, room)
    for row in rows:
        if row.status == "open" and not row.resolution_count:
            generate_options(session, row, room)
    return [conflict_out(row) for row in rows]


@router.post("/rooms/{room_id}/conflicts/refresh", response_model=ConflictRefreshOut,
             summary="按确认条件和候选活动刷新冲突")
def refresh(room_id: UUID, body: ConflictRefreshRequest, user: User = Depends(current_user),
            session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    rows = refresh_conflicts(session, room, include_theme_rules=body.include_theme_rules,
                             include_interest_clash=body.include_interest_clash, bump=True)
    return ConflictRefreshOut(room_version=room.version,
                              conflicts=[conflict_out(row) for row in rows],
                              issues=issues_from_conflicts(rows))


@router.get("/rooms/{room_id}/conflicts/{conflict_id}/resolutions", response_model=ResolutionsOut,
            summary="查看冲突解法选项")
def resolutions(room_id: UUID, conflict_id: UUID, user: User = Depends(current_user),
                session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    room = session.get(Room, room_id)
    conflict = _conflict(session, room_id, conflict_id)
    options = generate_options(session, conflict, room)
    return ResolutionsOut(conflict_id=conflict.id, room_version=room.version,
                          options=[ResolutionOut.model_validate(option) for option in options])


@router.post("/rooms/{room_id}/conflicts/{conflict_id}/resolve", response_model=ResolveResult,
             summary="应用冲突解法")
def resolve(room_id: UUID, conflict_id: UUID, body: ResolveRequest, user: User = Depends(current_user),
            session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    conflict = _conflict(session, room_id, conflict_id)
    option = session.get(ConflictOption, body.option_id)
    if option is None or option.conflict_id != conflict.id:
        raise ApiError(404, "OPTION_NOT_FOUND", "解法选项不存在")
    if option.feasibility == "infeasible":
        raise ApiError(422, "OPTION_INFEASIBLE", "该解法当前不可行")
    required = {UUID(str(item)) for item in (option.required_member_ids or [])}
    affected = {UUID(str(item)) for item in (option.affected_member_ids or [])}
    if option.action == "relax" and required <= {member.id}:
        apply_relax(session, room, conflict, option, member)
        return ResolveResult(effect="applied", room_version=room.version,
                             version_id=None, proposal_id=None, pending_member_ids=[])
    version = create_pending_version(session, room, conflict, option, member, body.comment)
    session.add(ConflictAction(room_id=room.id, conflict_id=conflict.id, option_id=option.id,
                               member_id=member.id, action=option.action, effect="pending_confirmation",
                               comment=body.comment))
    session.commit()
    return ResolveResult(effect="pending_confirmation", room_version=room.version,
                         version_id=version.id, proposal_id=None,
                         pending_member_ids=sorted(required or affected, key=str))
