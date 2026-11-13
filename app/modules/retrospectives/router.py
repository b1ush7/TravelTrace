from datetime import timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import (
    ActivityFact, Claim, Conflict, ConflictAction, Job, Member, MemberInterest, PlanVersion,
    Retrospective, Room, RoomTemplate, User, utcnow,
)
from app.db.session import get_session
from app.modules.plans.service import build_plan, current_published, parse_dt
from app.modules.retrospectives.schemas import (
    ArchiveInput, Concession, FromTemplateInput, PlannedVsActual, RetroCost, RetrospectiveOut,
    RoomTemplateOut,
)
from app.modules.rooms.schemas import RoomResponse
from app.modules.rooms.service import check_room_version, ensure_writable, lock_room, present_room, require_member, require_owner
from app.modules.themes import catalog as themes

router = APIRouter(tags=["复盘与模板"])


def _retro_payload(session: Session, room: Room, version: PlanVersion) -> dict:
    items = version.activities or []
    skipped = sum(1 for item in items if item.get("execution_state") == "skipped")
    completed = sum(1 for item in items if item.get("execution_state") == "completed")
    members = session.scalars(select(Member).where(Member.room_id == room.id,
                                                   Member.status == "active")).all()
    resolved = len(session.scalars(select(Conflict).where(
        Conflict.room_id == room.id, Conflict.status == "resolved")).all())
    actions = session.scalars(select(ConflictAction).where(ConflictAction.room_id == room.id)).all()
    counts: dict[UUID, int] = {}
    for action in actions:
        if action.effect == "applied":
            counts[action.member_id] = counts.get(action.member_id, 0) + 1
    estimated = float(version.estimated_cost_cny or 0)
    return {
        "room_id": str(room.id),
        "version_id": str(version.id),
        "planned_vs_actual": {
            "on_time_rate": round(completed / len(items), 4) if items else 0.0,
            "changed_activities": 0,
            "skipped_activities": skipped,
        },
        "cost": {
            "estimated_cny": estimated,
            "actual_cny": estimated,
            "per_person_cny": round(estimated / len(members), 2) if members else 0.0,
        },
        "conflicts_resolved": resolved,
        "concessions": [{"member_id": str(member_id), "count": count}
                        for member_id, count in sorted(counts.items(), key=lambda pair: str(pair[0]))],
        "highlights": [item.get("title", "") for item in items[:3] if item.get("title")],
        "generated_at": utcnow().isoformat(),
    }


def _create_template(session: Session, room: Room, version: PlanVersion, owner: Member) -> RoomTemplate:
    existing = session.scalar(select(RoomTemplate).where(RoomTemplate.source_room_id == room.id))
    if existing is not None:
        return existing
    codes = [row.tag_code for row in session.scalars(select(MemberInterest).where(
        MemberInterest.user_id == owner.user_id)).all()]
    for code in room.seed_interest_tag_codes or []:
        if code not in codes:
            codes.append(code)
    items = []
    for item in version.activities or []:
        if item.get("kind") != "activity":
            continue
        items.append({
            "place_name": item.get("place_name", ""),
            "place_id": None,
            "duration_minutes": max(0, int((parse_dt(item.get("ends_at")) - parse_dt(item.get("starts_at"))).total_seconds() // 60)) if parse_dt(item.get("starts_at")) and parse_dt(item.get("ends_at")) else 60,
            "estimated_cost_cny": float(item.get("estimated_cost_cny") or 0),
        })
    template = RoomTemplate(
        owner_user_id=owner.user_id, name=f"{room.name} 模板", source_room_id=room.id,
        destination=room.destination, theme_code=room.theme_code,
        days=(room.end_date - room.start_date).days + 1, member_count=len(
            session.scalars(select(Member).where(Member.room_id == room.id,
                                                 Member.status == "active")).all()),
        interest_tag_codes=codes, items=items,
    )
    session.add(template)
    return template


@router.post("/rooms/{room_id}/archive", response_model=RetrospectiveOut, summary="归档房间并生成复盘")
def archive(room_id: UUID, body: ArchiveInput, user: User = Depends(current_user),
            session: Session = Depends(get_session)):
    room, owner = require_owner(session, room_id, user.id)
    room = lock_room(session, room_id)
    if room.status == "archived":
        raise ApiError(409, "ROOM_ARCHIVED", "房间已归档")
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    version = current_published(session, room.id)
    if version is None:
        raise ApiError(409, "NO_PUBLISHED_VERSION", "没有可复盘的生效版本")
    generated_at = utcnow()
    payload = _retro_payload(session, room, version)
    payload["generated_at"] = generated_at.isoformat()
    retro = Retrospective(room_id=room.id, version_id=version.id, payload=payload,
                          generated_at=generated_at)
    session.add(retro)
    _create_template(session, room, version, owner)
    room.status = "archived"
    room.archived_at = utcnow()
    room.updated_at = utcnow()
    session.commit()
    return RetrospectiveOut.model_validate(payload)


@router.get("/rooms/{room_id}/retrospective", response_model=RetrospectiveOut, summary="查看旅行复盘")
def retrospective(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    row = session.scalar(select(Retrospective).where(Retrospective.room_id == room_id))
    if row is None:
        raise ApiError(404, "RETROSPECTIVE_NOT_FOUND", "复盘尚未生成")
    return RetrospectiveOut.model_validate(row.payload)


@router.get("/me/templates", response_model=list[RoomTemplateOut], summary="查看我的模板")
def my_templates(user: User = Depends(current_user), session: Session = Depends(get_session)):
    rows = session.scalars(select(RoomTemplate).where(RoomTemplate.owner_user_id == user.id)
                           .order_by(RoomTemplate.last_used_at.desc(), RoomTemplate.created_at.desc())
                           .limit(50)).all()
    return rows


@router.post("/rooms/from-template", response_model=RoomResponse, summary="从模板创建房间")
def from_template(body: FromTemplateInput, user: User = Depends(current_user),
                  session: Session = Depends(get_session)):
    template = session.get(RoomTemplate, body.template_id)
    if template is None or template.owner_user_id != user.id:
        raise ApiError(404, "TEMPLATE_NOT_FOUND", "模板不存在")
    if body.end_date < body.start_date:
        raise ApiError(422, "VALIDATION_ERROR", "结束日期不能早于开始日期")
    room = Room(name=body.name, destination=template.destination, start_date=body.start_date,
                end_date=body.end_date, theme_code=template.theme_code,
                seed_interest_tag_codes=template.interest_tag_codes, owner_id=user.id,
                status="planning")
    session.add(room)
    session.flush()
    owner = Member(room_id=room.id, user_id=user.id, display_name=user.display_name, role="owner")
    session.add(owner)
    session.flush()
    facts = []
    for item in template.items or []:
        fact = ActivityFact(room_id=room.id, owner_member_id=owner.id,
                            name=item.get("place_name", "活动"),
                            place_name=item.get("place_name", ""),
                            duration_minutes=int(item.get("duration_minutes") or 60),
                            estimated_cost_cny=float(item.get("estimated_cost_cny") or 0),
                            cost_scope="per_person", source_note="来自模板")
        session.add(fact)
        facts.append(fact)
    template.last_used_at = utcnow()
    session.flush()
    if facts:
        job = Job(room_id=room.id, kind="plan", status="running", stage="solving",
                  input={"template_id": str(template.id)})
        session.add(job)
        session.flush()
        class _Body:
            activity_ids = [fact.id for fact in facts]
            theme_code = template.theme_code
            allow_split = False
            interest_weight = 0.5
            must_tag_codes = []
            avoid_tag_codes = []
        build_plan(session, room, owner, _Body(), job)
    else:
        session.commit()
    return present_room(session, room)