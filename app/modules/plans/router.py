from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import ActivityFact, ExecutionRecord, Job, Member, PlanVersion, Room, User, utcnow
from app.db.session import get_session
from app.modules.claims.schemas import ClaimOut
from app.modules.plans.schemas import (
    ActivityInput, ActivityOut, ExecutionInput, ExecutionOut, InitialPlanInput, LocalChangeInput,
    NextStepOut, PlanDecisionIn, PlanRevisionIn, PlanValidationOut, PlanVersionOut, PlanningJobOut,
    RoomOverviewV06Out,
)
from app.modules.plans.service import (
    activity_out, build_plan, build_replan, current_published, next_step, overview, parse_dt,
    planning_job_out, publish, validation, version_out,
)
from app.modules.rooms.service import (
    check_room_version, ensure_writable, lock_room, require_member, require_owner,
)

router = APIRouter(tags=["行程规划"])


def _activity(session: Session, room_id: UUID, activity_id: UUID) -> ActivityFact:
    fact = session.get(ActivityFact, activity_id)
    if fact is None or fact.room_id != room_id:
        raise ApiError(404, "ACTIVITY_NOT_FOUND", "候选活动不存在")
    return fact


def _version(session: Session, room_id: UUID, version_id: UUID) -> PlanVersion:
    version = session.get(PlanVersion, version_id)
    if version is None or version.room_id != room_id:
        raise ApiError(404, "VERSION_NOT_FOUND", "行程版本不存在")
    return version


@router.get("/rooms/{room_id}/activities", response_model=list[ActivityOut], summary="查看候选活动与固定安排")
def list_activities(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    room = session.get(Room, room_id)
    facts = session.scalars(select(ActivityFact).where(ActivityFact.room_id == room_id)
                            .order_by(ActivityFact.created_at, ActivityFact.id)).all()
    return [activity_out(fact, room.version) for fact in facts]


@router.post("/rooms/{room_id}/activities", response_model=ActivityOut, status_code=201,
             summary="手动录入候选活动")
def create_activity(room_id: UUID, body: ActivityInput, user: User = Depends(current_user),
                    session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    fact = ActivityFact(room_id=room_id, owner_member_id=member.id, name=body.name,
                        place_name=body.place_name, place_id=body.place_id,
                        duration_minutes=body.duration_minutes,
                        estimated_cost_cny=body.estimated_cost_cny, cost_scope=body.cost_scope,
                        window_start=body.window_start, window_end=body.window_end,
                        reserved_start=body.reserved_start, reservation_status=body.reservation_status,
                        source_note=body.source_note)
    session.add(fact)
    room.version += 1
    room.updated_at = utcnow()
    session.commit()
    return activity_out(fact, room.version)


@router.put("/rooms/{room_id}/activities/{activity_id}", response_model=ActivityOut,
            summary="更新本人录入的候选活动")
def update_activity(room_id: UUID, activity_id: UUID, body: ActivityInput,
                    user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    fact = _activity(session, room_id, activity_id)
    if fact.owner_member_id != member.id:
        raise ApiError(403, "NOT_ACTIVITY_OWNER", "只能修改本人录入的活动")
    fact.name = body.name
    fact.place_name = body.place_name
    fact.place_id = body.place_id
    fact.duration_minutes = body.duration_minutes
    fact.estimated_cost_cny = body.estimated_cost_cny
    fact.cost_scope = body.cost_scope
    fact.window_start = body.window_start
    fact.window_end = body.window_end
    fact.reserved_start = body.reserved_start
    fact.reservation_status = body.reservation_status
    fact.source_note = body.source_note
    room.version += 1
    room.updated_at = utcnow()
    session.commit()
    return activity_out(fact, room.version)


@router.post("/rooms/{room_id}/plan-jobs", response_model=PlanningJobOut, status_code=202,
             summary="生成多人行程候选")
def create_plan_job(room_id: UUID, body: InitialPlanInput, user: User = Depends(current_user),
                    session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    job = Job(room_id=room_id, kind="plan", status="running", stage="solving",
              input=body.model_dump(mode="json"))
    session.add(job)
    session.flush()
    try:
        build_plan(session, room, member, body, job)
    except ApiError:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        job = Job(room_id=room_id, kind="plan", status="failed", stage="finished",
                  error="规划任务失败", input=body.model_dump(mode="json"))
        session.add(job)
        session.commit()
        raise ApiError(500, "PLAN_FAILED", "规划任务失败")
    return planning_job_out(job)


@router.get("/rooms/{room_id}/jobs/{job_id}", response_model=PlanningJobOut,
            summary="查询规划任务状态与结果")
def get_job(room_id: UUID, job_id: UUID, user: User = Depends(current_user),
            session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    job = session.get(Job, job_id)
    if job is None or job.room_id != room_id:
        raise ApiError(404, "JOB_NOT_FOUND", "任务不存在")
    return planning_job_out(job)


@router.delete("/rooms/{room_id}/jobs/{job_id}", response_model=PlanningJobOut,
               summary="取消未完成的规划任务")
def cancel_job(room_id: UUID, job_id: UUID, user: User = Depends(current_user),
               session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    job = session.get(Job, job_id)
    if job is None or job.room_id != room_id:
        raise ApiError(404, "JOB_NOT_FOUND", "任务不存在")
    if job.status not in {"queued", "running"}:
        raise ApiError(409, "JOB_NOT_CANCELLABLE", "当前任务状态不能取消")
    job.status = "cancelled"
    job.stage = "finished"
    job.progress_message = "已取消"
    session.commit()
    return planning_job_out(job)


@router.get("/rooms/{room_id}/trip-versions", response_model=list[PlanVersionOut],
            summary="查看候选及历史行程")
def list_versions(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    rows = session.scalars(select(PlanVersion).where(PlanVersion.room_id == room_id)
                           .order_by(PlanVersion.created_at.desc(), PlanVersion.id)).all()
    return [version_out(row) for row in rows]


@router.get("/rooms/{room_id}/trip-versions/current", response_model=PlanVersionOut,
            summary="查看当前生效行程")
def current_version(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    version = current_published(session, room_id)
    if version is None:
        raise ApiError(404, "NO_PUBLISHED_VERSION", "房间还没有生效版本")
    return version_out(version)


@router.get("/rooms/{room_id}/trip-versions/{version_id}", response_model=PlanVersionOut,
            summary="查看行程、分支及变更影响")
def version_detail(room_id: UUID, version_id: UUID, user: User = Depends(current_user),
                   session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    return version_out(_version(session, room_id, version_id))


@router.get("/rooms/{room_id}/trip-versions/{version_id}/validation", response_model=PlanValidationOut,
            summary="查看行程可行性校验")
def version_validation(room_id: UUID, version_id: UUID, user: User = Depends(current_user),
                       session: Session = Depends(get_session)):
    require_member(session, room_id, user.id)
    return validation(session, _version(session, room_id, version_id))


@router.post("/rooms/{room_id}/trip-versions/{version_id}/confirmation", response_model=PlanVersionOut,
             summary="提交本人对行程提案的决定")
def confirm_version(room_id: UUID, version_id: UUID, body: PlanDecisionIn,
                    user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    version = _version(session, room_id, version_id)
    current = current_published(session, room_id)
    if (current.id if current else None) != body.expected_current_version_id:
        raise ApiError(409, "VERSION_CONFLICT", "当前生效版本已变化")
    if version.status != "awaiting_confirmation":
        raise ApiError(409, "VERSION_NOT_CONFIRMABLE", "当前版本状态不能确认")
    approvals = [dict(item) for item in (version.approvals or [])]
    target = next((item for item in approvals if str(item.get("member_id")) == str(member.id)), None)
    if target is None:
        raise ApiError(403, "NOT_REQUIRED_MEMBER", "该版本不需要你确认")
    target["decision"] = body.decision
    target["decided_at"] = utcnow().isoformat()
    target["comment"] = body.comment or ""
    version.approvals = approvals
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(version, "approvals")
    if body.decision == "reject":
        version.status = "rejected"
    version.updated_at = utcnow()
    session.commit()
    return version_out(version)


@router.post("/rooms/{room_id}/trip-versions/{version_id}/publish", response_model=PlanVersionOut,
             summary="发布已取得必要确认的行程")
def publish_version(room_id: UUID, version_id: UUID, body: PlanRevisionIn,
                    user: User = Depends(current_user), session: Session = Depends(get_session)):
    room, member = require_owner(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    current = current_published(session, room_id)
    if (current.id if current else None) != body.expected_current_version_id:
        raise ApiError(409, "VERSION_CONFLICT", "当前生效版本已变化")
    version = _version(session, room_id, version_id)
    return version_out(publish(session, room, version, member))


@router.post("/rooms/{room_id}/trip-versions/{version_id}/cancel", response_model=PlanVersionOut,
             summary="取消未生效的行程提案")
def cancel_version(room_id: UUID, version_id: UUID, body: PlanRevisionIn,
                   user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    version = _version(session, room_id, version_id)
    current = current_published(session, room_id)
    if (current.id if current else None) != body.expected_current_version_id:
        raise ApiError(409, "VERSION_CONFLICT", "当前生效版本已变化")
    if version.status == "published":
        raise ApiError(409, "VERSION_PUBLISHED", "已发布版本不能取消")
    if member.role != "owner" and version.proposer_member_id != member.id:
        raise ApiError(403, "NOT_PROPOSER", "只有提案人或房主可以取消")
    version.status = "cancelled"
    version.updated_at = utcnow()
    session.commit()
    return version_out(version)


@router.get("/rooms/{room_id}/next-step", response_model=NextStepOut, summary="查看本人下一步与集合点")
def room_next_step(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = session.get(Room, room_id)
    return next_step(session, room, member)


@router.get("/rooms/{room_id}/overview", response_model=RoomOverviewV06Out,
            summary="查看房间的条件、冲突及生效状态")
def room_overview(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = session.get(Room, room_id)
    return overview(session, room, member)

@router.post("/rooms/{room_id}/replan-jobs", response_model=PlanningJobOut, status_code=202,
             summary="预演途中局部变更")
def create_replan_job(room_id: UUID, body: LocalChangeInput, user: User = Depends(current_user),
                      session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    job = Job(room_id=room_id, kind="replan", status="running", stage="solving",
              input=body.model_dump(mode="json"))
    session.add(job)
    session.flush()
    try:
        build_replan(session, room, member, body, job)
    except ApiError:
        session.rollback()
        raise
    return planning_job_out(job)


@router.put("/rooms/{room_id}/trip-versions/current/activities/{activity_id}/execution",
            response_model=ExecutionOut, summary="记录本人活动进度")
def record_execution(room_id: UUID, activity_id: UUID, body: ExecutionInput,
                     user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    version = current_published(session, room_id)
    if version is None:
        raise ApiError(404, "NO_PUBLISHED_VERSION", "房间还没有生效版本")
    if version.id != body.expected_current_version_id:
        raise ApiError(409, "VERSION_CONFLICT", "当前生效版本已变化")
    item = next((row for row in (version.activities or []) if str(row.get("id")) == str(activity_id)), None)
    if item is None:
        raise ApiError(404, "ACTIVITY_NOT_FOUND", "当前版本中不存在该活动")
    if str(member.id) not in [str(value) for value in item.get("member_ids", [])]:
        raise ApiError(403, "NOT_ACTIVITY_PARTICIPANT", "你不是该活动的参与者")
    record = session.scalar(select(ExecutionRecord).where(
        ExecutionRecord.version_id == version.id, ExecutionRecord.activity_id == activity_id,
        ExecutionRecord.member_id == member.id))
    if record is not None and record.state == body.state:
        return ExecutionOut(activity_id=activity_id, member_id=member.id, current_version_id=version.id,
                            room_version=room.version, state=record.state, updated_at=record.updated_at)
    if record is None:
        record = ExecutionRecord(room_id=room_id, version_id=version.id, activity_id=activity_id,
                                 member_id=member.id, state=body.state)
        session.add(record)
    else:
        record.state = body.state
        record.updated_at = utcnow()
    item["execution_state"] = "completed" if body.state == "completed" else "in_progress"
    flag_modified(version, "activities")
    room.version += 1
    room.updated_at = utcnow()
    session.commit()
    return ExecutionOut(activity_id=activity_id, member_id=member.id, current_version_id=version.id,
                        room_version=room.version, state=record.state, updated_at=record.updated_at)
