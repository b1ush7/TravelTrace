from __future__ import annotations

import copy
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import (
    ActivityFact, Claim, Conflict, Job, Member, Participation, PlanVersion, Room, User, utcnow,
)
from app.modules.claims.service import claim_out
from app.modules.conflicts.service import issues_from_conflicts
from app.modules.interests.service import room_overview
from app.modules.plans.schemas import (
    ActivityOut, NextStepOut, PlanValidationOut, PlanVersionOut, PlanningJobOut, RoomOverviewV06Out,
)
from app.modules.rooms.service import present_room
from app.modules.themes import catalog as themes

DEFAULT_TZ = "Asia/Shanghai"


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def current_published(session: Session, room_id: UUID) -> PlanVersion | None:
    return session.scalar(select(PlanVersion).where(
        PlanVersion.room_id == room_id, PlanVersion.status == "published",
    ).order_by(PlanVersion.published_at.desc(), PlanVersion.created_at.desc()))


def activities(version: PlanVersion | None) -> list[dict]:
    if version is None:
        return []
    return sorted(version.activities or [],
                  key=lambda item: parse_dt(item.get("starts_at")) or datetime.max.replace(tzinfo=timezone.utc))


def next_meeting(version: PlanVersion | None, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    meetings = []
    for item in activities(version):
        if item.get("kind") != "meeting":
            continue
        start = parse_dt(item.get("starts_at"))
        if start and start >= now:
            meetings.append((start, item))
    if not meetings:
        return None
    start, item = meetings[0]
    return {"title": item.get("title", "集合"), "place_name": item.get("place_name", ""), "at": start}


def activity_out(fact: ActivityFact, room_version: int) -> ActivityOut:
    return ActivityOut(
        id=fact.id, owner_member_id=fact.owner_member_id, name=fact.name, place_name=fact.place_name,
        place_id=fact.place_id, duration_minutes=fact.duration_minutes,
        estimated_cost_cny=fact.estimated_cost_cny, cost_scope=fact.cost_scope,
        window_start=fact.window_start, window_end=fact.window_end, reserved_start=fact.reserved_start,
        reservation_status=fact.reservation_status, source_type="manual", source_note=fact.source_note,
        observed_at=fact.created_at, room_version=room_version)


def version_out(version: PlanVersion) -> PlanVersionOut:
    return PlanVersionOut.model_validate(version)


def _active_members(session: Session, room_id: UUID) -> list[Member]:
    return list(session.scalars(select(Member).where(Member.room_id == room_id,
                                                     Member.status == "active")).all())


def _schedule(room: Room, facts: list[ActivityFact]) -> list[dict]:
    tz = ZoneInfo(room.time_zone or DEFAULT_TZ)
    day = room.start_date
    cursor = datetime.combine(day, time(9, 0), tzinfo=tz)
    members = []
    items = [{
        "id": str(uuid4()), "activity_id": None, "title": "集合出发", "place_name": room.destination,
        "map_place_id": None, "starts_at": datetime.combine(day, time(8, 30), tzinfo=tz).isoformat(),
        "ends_at": cursor.isoformat(), "member_ids": members, "branch_id": None, "kind": "meeting",
        "commitment": "flexible", "execution_state": "planned", "estimated_cost_cny": 0.0,
        "source_note": "行程骨架自动生成的集合点",
    }]
    for fact in facts:
        duration = max(fact.duration_minutes or 30, 15)
        end = cursor + timedelta(minutes=duration)
        if cursor.hour >= 19 or end.date() > cursor.date():
            day = min(day + timedelta(days=1), room.end_date)
            cursor = datetime.combine(day, time(9, 0), tzinfo=tz)
            end = cursor + timedelta(minutes=duration)
        items.append({
            "id": str(uuid4()), "activity_id": str(fact.id), "title": fact.name,
            "place_name": fact.place_name, "map_place_id": fact.place_id,
            "starts_at": cursor.isoformat(), "ends_at": end.isoformat(), "member_ids": members,
            "branch_id": None, "kind": "activity",
            "commitment": "fixed" if (fact.reservation_status == "confirmed" or fact.reserved_start) else "flexible",
            "execution_state": "planned", "estimated_cost_cny": fact.estimated_cost_cny,
            "source_note": fact.source_note,
        })
        cursor = end + timedelta(minutes=30)
    return items


def _connections(items: list[dict]) -> list[dict]:
    result = []
    for first, second in zip(items, items[1:]):
        if first["kind"] != "activity" and second["kind"] != "activity":
            continue
        result.append({
            "from_id": first["id"], "to_id": second["id"], "member_ids": second["member_ids"],
            "kind": "travel", "travel_minutes": 20, "source": "estimate",
        })
    return result


def build_plan(session: Session, room: Room, member: Member, body, job: Job) -> PlanVersion:
    facts = list(session.scalars(select(ActivityFact).where(
        ActivityFact.room_id == room.id, ActivityFact.id.in_(body.activity_ids))).all())
    if len(facts) != len(set(body.activity_ids)):
        raise ApiError(404, "ACTIVITY_NOT_FOUND", "候选活动不存在")
    facts.sort(key=lambda fact: (fact.window_start or fact.created_at, fact.created_at))
    theme_code = body.theme_code or room.theme_code
    if theme_code and not themes.exists(theme_code):
        raise ApiError(422, "THEME_NOT_FOUND", "主题不存在")
    if theme_code and themes.city_scope(theme_code) != room.destination:
        raise ApiError(422, "THEME_CITY_MISMATCH", "主题与目的地不匹配")
    members = _active_members(session, room.id)
    member_ids = [str(item.id) for item in members]
    items = _schedule(room, facts)
    for item in items:
        item["member_ids"] = member_ids
    connections = _connections(items)
    connections_members = [item["member_ids"] for item in connections]
    for index, connection in enumerate(connections):
        connection["member_ids"] = connections_members[index]
    participation = [{"member_id": str(row.member_id), "joins_at": row.joins_at.isoformat(),
                      "leaves_at": row.leaves_at.isoformat(), "allow_solo": row.allow_solo,
                      "room_version": room.version}
                     for row in session.scalars(select(Participation).where(
                         Participation.room_id == room.id)).all()]
    estimated = sum(float(item.get("estimated_cost_cny") or 0) for item in items)
    version = PlanVersion(
        room_id=room.id, proposer_member_id=member.id, base_version_id=None,
        input_room_version=room.version, status="awaiting_confirmation", theme_code=theme_code,
        activities=items, connections=connections,
        split_segments=[], participation=participation, estimated_cost_cny=estimated,
        member_budgets=[], unknowns=[], impact={
            "changed_activity_ids": [], "affected_member_ids": [], "required_member_ids": [],
            "changed_commitment_ids": [], "cost_delta_cny": None, "time_delta_minutes": None,
            "unknowns": [] if participation else ["参与区间未填写"],
        },
        approvals=[{"member_id": str(item.id), "decision": "pending", "decided_at": None, "comment": ""}
                   for item in members],
        card_summary={"title": f"{room.name} 行程待确认", "subtitle": f"{len(items)} 个安排",
                      "at": utcnow().isoformat()},
        expires_at=utcnow() + timedelta(hours=48),
    )
    session.add(version)
    session.flush()
    job.status = "succeeded"
    job.outcome = "feasible"
    job.stage = "finished"
    job.result_version_id = version.id
    job.progress_message = "候选已生成，等待成员确认"
    room.status = "planning"
    room.updated_at = utcnow()
    session.commit()
    return version


def planning_job_out(job: Job) -> PlanningJobOut:
    issues = []
    if job.status == "failed":
        issues = [{"code": "JOB_FAILED", "message": job.error or "任务失败", "severity": "error",
                   "member_ids": [], "activity_ids": [], "adjustment_options": []}]
    return PlanningJobOut(id=job.id, status=job.status, outcome=job.outcome, stage=job.stage,
                          result_version_id=job.result_version_id, issues=issues)


def validation(session: Session, version: PlanVersion) -> PlanValidationOut:
    conflicts = list(session.scalars(select(Conflict).where(
        Conflict.room_id == version.room_id, Conflict.status == "open")).all())
    issues = [item.model_dump(mode="json") for item in issues_from_conflicts(conflicts)]
    high = any(row.severity == "error" for row in conflicts)
    return PlanValidationOut(version_id=version.id,
                             outcome="infeasible" if high else ("unknown" if not version.activities else "feasible"),
                             issues=issues)


def publish(session: Session, room: Room, version: PlanVersion, actor: Member) -> PlanVersion:
    if version.room_id != room.id:
        raise ApiError(404, "VERSION_NOT_FOUND", "行程版本不存在")
    if version.status not in {"awaiting_confirmation", "draft"}:
        raise ApiError(409, "VERSION_NOT_PUBLISHABLE", "当前版本状态不能发布")
    pending = [item for item in (version.approvals or []) if item.get("decision") == "pending"]
    rejected = [item for item in (version.approvals or []) if item.get("decision") in {"reject", "request_changes"}]
    if pending or rejected:
        raise ApiError(409, "CONFIRMATION_INCOMPLETE", "仍有成员未确认或要求修改")
    previous = current_published(session, room.id)
    if previous is not None:
        previous.status = "superseded"
    version.status = "published"
    version.published_at = utcnow()
    room.version += 1
    room.status = "published"
    room.updated_at = utcnow()
    session.flush()
    from app.modules.reach.service import notify_publish
    notify_publish(session, room, version)
    session.commit()
    return version


def next_step(session: Session, room: Room, member: Member) -> NextStepOut:
    version = current_published(session, room.id)
    if version is None:
        raise ApiError(404, "NO_PUBLISHED_VERSION", "房间还没有生效版本")
    now = datetime.now(timezone.utc)
    items = activities(version)
    upcoming = next((item for item in items if (parse_dt(item.get("starts_at")) or now) > now), None)
    meeting = next_meeting(version, now)
    next_out = PlanVersionOut.model_validate(version)
    next_activity = None
    if upcoming is not None:
        next_activity = next((item for item in next_out.activities
                              if str(item.id) == str(upcoming.get("id"))), None)
    meeting_activity = None
    if meeting is not None:
        meeting_activity = next((item for item in next_out.activities
                                 if item.kind == "meeting" and item.starts_at == meeting["at"]), None)
    departure = None
    if upcoming is not None:
        departure = (parse_dt(upcoming.get("starts_at")) or now) - timedelta(minutes=30)
    target = meeting["place_name"] if meeting else (upcoming.get("place_name") if upcoming else None)
    from app.modules.reach.service import build_live_state
    return NextStepOut(
        current_version_id=version.id, next_activity=next_activity, departure_at=departure,
        meeting_activity=meeting_activity,
        navigation_url=f"https://maps.traveltrace.demo/search?q={quote(target)}" if target else None,
        synced_at=now, live=build_live_state(room, version, member),
        theme={"code": room.theme_code, "name": themes.name(room.theme_code)} if room.theme_code and themes.exists(room.theme_code) else None,
        deep_link=f"traveltrace://room/{room.id}",
    )


def overview(session: Session, room: Room, member: Member) -> RoomOverviewV06Out:
    tz = ZoneInfo(room.time_zone or DEFAULT_TZ)
    schedule = {
        "starts_at": (room.window_starts_at or datetime.combine(room.start_date, time(0, 0), tzinfo=tz)).isoformat(),
        "ends_at": (room.window_ends_at or datetime.combine(room.end_date, time(23, 59, 59), tzinfo=tz)).isoformat(),
        "time_zone": room.time_zone or DEFAULT_TZ, "room_version": room.version,
    }
    participation = [{"member_id": row.member_id, "joins_at": row.joins_at, "leaves_at": row.leaves_at,
                      "allow_solo": row.allow_solo, "room_version": room.version}
                     for row in session.scalars(select(Participation).where(
                         Participation.room_id == room.id)).all()]
    claims = [claim_out(row) for row in session.scalars(select(Claim).where(
        Claim.room_id == room.id).order_by(Claim.created_at)).all()]
    conflicts = list(session.scalars(select(Conflict).where(Conflict.room_id == room.id)).all())
    open_conflicts = [row for row in conflicts if row.status == "open"]
    issues = [item.model_dump(mode="json") for item in issues_from_conflicts(conflicts)]
    version = current_published(session, room.id)
    pending = list(session.scalars(select(PlanVersion).where(
        PlanVersion.room_id == room.id, PlanVersion.status == "awaiting_confirmation")).all())
    interest = room_overview(session, room)
    key_members = []
    for row in open_conflicts:
        for member_id in row.key_member_ids or []:
            parsed = UUID(str(member_id))
            if parsed not in key_members:
                key_members.append(parsed)
    from app.modules.reach.service import build_live_state
    meeting = next_meeting(version)
    return RoomOverviewV06Out(
        room=present_room(session, room), schedule=schedule, participation=participation, claims=claims,
        conflicts=issues, current_version_id=version.id if version else None,
        pending_plans=[version_out(row) for row in pending], theme_code=room.theme_code,
        interests=interest if interest.filled_member_count else None,
        conflict_summary={"open": len(open_conflicts), "resolved": len(conflicts) - len(open_conflicts),
                          "key_member_ids": key_members},
        live=build_live_state(room, version, member) if version else None,
        next_meeting={"title": meeting["title"], "place_name": meeting["place_name"], "at": meeting["at"]}
        if meeting else None,
    )

def build_replan(session: Session, room: Room, member: Member, body, job: Job) -> PlanVersion:
    base = session.get(PlanVersion, body.base_version_id)
    if base is None or base.room_id != room.id:
        raise ApiError(404, "VERSION_NOT_FOUND", "基准版本不存在")
    items = copy.deepcopy(base.activities or [])
    connections = copy.deepcopy(base.connections or [])
    participation = copy.deepcopy(base.participation or [])
    changed_ids: list[str] = []
    affected: set[str] = set()
    required: set[str] = set()
    cost_delta = 0.0
    time_delta = 0

    def find(activity_id):
        target = next((item for item in items if str(item.get("id")) == str(activity_id)), None)
        if target is None:
            raise ApiError(404, "ACTIVITY_NOT_FOUND", "版本中的活动不存在")
        return target

    if body.operation in {"replace", "skip", "resize"} and body.target_activity_id is None:
        raise ApiError(422, "VALIDATION_ERROR", "该操作需要 target_activity_id")
    if body.operation == "replace":
        if body.replacement_activity_id is None:
            raise ApiError(422, "VALIDATION_ERROR", "replace 需要 replacement_activity_id")
        target = find(body.target_activity_id)
        replacement = session.get(ActivityFact, body.replacement_activity_id)
        if replacement is None or replacement.room_id != room.id:
            raise ApiError(404, "ACTIVITY_NOT_FOUND", "替代活动不存在")
        cost_delta = float(replacement.estimated_cost_cny or 0) - float(target.get("estimated_cost_cny") or 0)
        target.update({
            "activity_id": str(replacement.id), "title": replacement.name,
            "place_name": replacement.place_name, "map_place_id": replacement.place_id,
            "estimated_cost_cny": replacement.estimated_cost_cny,
            "source_note": replacement.source_note,
            "commitment": "fixed" if replacement.reservation_status == "confirmed" else "flexible",
        })
        changed_ids.append(str(target["id"]))
        affected.update(str(item) for item in target.get("member_ids", []))
    elif body.operation == "skip":
        target = find(body.target_activity_id)
        items = [item for item in items if str(item.get("id")) != str(target["id"])]
        changed_ids.append(str(target["id"]))
        affected.update(str(item) for item in target.get("member_ids", []))
        cost_delta = -float(target.get("estimated_cost_cny") or 0)
    elif body.operation == "resize":
        if body.duration_minutes is None:
            raise ApiError(422, "VALIDATION_ERROR", "resize 需要 duration_minutes")
        target = find(body.target_activity_id)
        start = parse_dt(target.get("starts_at"))
        old_end = parse_dt(target.get("ends_at"))
        new_end = start + timedelta(minutes=body.duration_minutes)
        delta = int((new_end - old_end).total_seconds() // 60)
        target["ends_at"] = new_end.isoformat()
        changed_ids.append(str(target["id"]))
        affected.update(str(item) for item in target.get("member_ids", []))
        for item in items:
            item_start = parse_dt(item.get("starts_at"))
            if item_start and item_start >= old_end and str(item.get("id")) != str(target["id"]):
                item["starts_at"] = (item_start + timedelta(minutes=delta)).isoformat()
                item["ends_at"] = (parse_dt(item.get("ends_at")) + timedelta(minutes=delta)).isoformat()
        time_delta = delta
    elif body.operation == "leave_early":
        if body.leaves_at is None:
            raise ApiError(422, "VALIDATION_ERROR", "leave_early 需要 leaves_at")
        leaves = body.leaves_at
        if leaves.tzinfo is None:
            leaves = leaves.replace(tzinfo=timezone.utc)
        for item in items:
            start = parse_dt(item.get("starts_at"))
            if start and start >= leaves:
                before = {str(value) for value in item.get("member_ids", [])}
                item["member_ids"] = [value for value in item.get("member_ids", []) if str(value) != str(member.id)]
                if before != {str(value) for value in item["member_ids"]}:
                    changed_ids.append(str(item["id"]))
        for row in participation:
            if str(row.get("member_id")) == str(member.id):
                row["leaves_at"] = leaves.isoformat()
        affected.add(str(member.id))
        required.add(str(member.id))
    elif body.operation == "restore":
        if body.restore_version_id is None:
            raise ApiError(422, "VALIDATION_ERROR", "restore 需要 restore_version_id")
        restored = session.get(PlanVersion, body.restore_version_id)
        if restored is None or restored.room_id != room.id:
            raise ApiError(404, "VERSION_NOT_FOUND", "历史版本不存在")
        items = copy.deepcopy(restored.activities or [])
        connections = copy.deepcopy(restored.connections or [])
        changed_ids = [str(item.get("id")) for item in items]
        for item in items:
            affected.update(str(value) for value in item.get("member_ids", []))

    if not required:
        required = set(affected)
    members = _active_members(session, room.id)
    if not required:
        required = {str(item.id) for item in members}
    version = PlanVersion(
        room_id=room.id, proposer_member_id=member.id, base_version_id=base.id,
        input_room_version=room.version, status="awaiting_confirmation", theme_code=room.theme_code,
        activities=items, connections=connections, split_segments=copy.deepcopy(base.split_segments or []),
        participation=participation, estimated_cost_cny=max(0.0, float(base.estimated_cost_cny or 0) + cost_delta),
        member_budgets=copy.deepcopy(base.member_budgets or []), unknowns=[],
        impact={"changed_activity_ids": changed_ids, "affected_member_ids": sorted(affected),
                "required_member_ids": sorted(required), "changed_commitment_ids": [],
                "cost_delta_cny": cost_delta, "time_delta_minutes": time_delta, "unknowns": []},
        approvals=[{"member_id": item, "decision": "pending", "decided_at": None, "comment": ""}
                   for item in sorted(required)],
        card_summary={"title": f"局部调整：{body.operation}", "subtitle": "等待受影响成员确认",
                      "at": utcnow().isoformat()},
        expires_at=utcnow() + timedelta(hours=24),
    )
    session.add(version)
    session.flush()
    job.status = "succeeded"
    job.outcome = "feasible"
    job.stage = "finished"
    job.result_version_id = version.id
    job.progress_message = "局部变更已预演，等待确认"
    room.updated_at = utcnow()
    session.commit()
    return version