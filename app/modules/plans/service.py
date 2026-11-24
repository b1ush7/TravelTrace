from __future__ import annotations

import copy
from datetime import datetime, time, timedelta, timezone
from urllib.parse import quote
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import (
    ActivityFact, Claim, Conflict, Job, Member, Participation, PlanVersion, Room, utcnow,
)
from app.modules.claims.service import claim_out
from app.modules.conflicts.service import issues_from_conflicts
from app.modules.interests.service import room_overview
from app.modules.plans.context import build_context
from app.modules.plans.schemas import (
    ActivityOut, NextStepOut, PlanValidationOut, PlanVersionOut, PlanningJobOut, RoomOverviewV06Out,
)
from app.modules.plans.solver import SolveResult, solve
from app.modules.plans.travel import travel_minutes
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


def _item_payload(item, room: Room) -> dict:
    """Map a solver item onto the plan-version JSON contract."""
    slot = item.slot
    return {
        "id": str(uuid4()), "activity_id": str(slot.activity_id) if slot else None,
        "title": item.title, "place_name": item.place_name,
        "map_place_id": slot.place_id if slot else None,
        "starts_at": item.start.isoformat(), "ends_at": item.end.isoformat(),
        "member_ids": [str(value) for value in item.member_ids],
        "branch_id": item.branch_id, "kind": item.kind,
        "commitment": "fixed" if slot and (slot.reservation_status == "confirmed"
                                           or slot.fixed_start) else "flexible",
        "execution_state": "planned",
        "estimated_cost_cny": slot.cost_cny if slot else 0.0,
        "source_note": slot.source_note if slot else "行程骨架自动生成的集合点",
    }


def _connections(items: list[dict], by_activity: dict) -> list[dict]:
    """Travel legs between consecutive items, with an explicit unknown source."""
    result = []
    for first, second in zip(items, items[1:]):
        if first["kind"] != "activity" and second["kind"] != "activity":
            continue
        first_slot = by_activity.get(first["activity_id"])
        second_slot = by_activity.get(second["activity_id"])
        minutes = None
        source = "unknown"
        if second_slot is not None:
            minutes, source = travel_minutes(first_slot, second_slot)
        if source == "unknown" and first_slot is not None:
            # A placeholder keeps the timeline realistic, but \`travel_minutes\`
            # stays null so validation still refuses to publish on it.
            minutes = None
        result.append({
            "from_id": first["id"], "to_id": second["id"], "member_ids": second["member_ids"],
            "kind": "travel", "travel_minutes": minutes, "source": source,
        })
    return result


def _estimate_cost(items: list[dict], slots: dict) -> tuple[float, list[dict]]:
    """Total cost plus per-member budget utilisation.

    `per_person` costs are multiplied by the attendee count; `total` costs are
    spread across attendees. The old planner summed raw values regardless of
    scope, so group totals and per-head budgets disagreed.
    """
    total = 0.0
    per_member: dict[str, float] = {}
    for item in items:
        if item["kind"] != "activity":
            continue
        slot = slots.get(item["activity_id"])
        if slot is None:
            continue
        people = max(len(item["member_ids"]), 1)
        amount = slot.cost_cny if slot.cost_scope == "per_person" else slot.cost_cny / people
        attendees = [str(value) for value in item["member_ids"]]
        share = slot.cost_cny * people if slot.cost_scope == "per_person" else slot.cost_cny
        total += share
        for member_id in attendees:
            per_member[member_id] = per_member.get(member_id, 0.0) + amount
    return total, [{"member_id": member_id, "estimated_cny": round(value, 2)}
                   for member_id, value in sorted(per_member.items())]


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
    context = build_context(session, room, facts)
    result = solve(context, allow_split=bool(body.allow_split))
    slots = {str(slot.activity_id): slot for slot in context.slots}
    items = [_item_payload(item, room) for item in result.items]
    connections = _connections(items, slots)
    participation = [{"member_id": str(row.member_id), "joins_at": row.joins_at.isoformat(),
                      "leaves_at": row.leaves_at.isoformat(), "allow_solo": row.allow_solo,
                      "room_version": room.version}
                     for row in session.scalars(select(Participation).where(
                         Participation.room_id == room.id)).all()]
    estimated, per_member = _estimate_cost(items, slots)
    issues = plan_issues(result, context)
    outcome = _outcome(result, issues)
    version = PlanVersion(
        room_id=room.id, proposer_member_id=member.id, base_version_id=None,
        input_room_version=room.version, status="awaiting_confirmation", theme_code=theme_code,
        activities=items, connections=connections,
        split_segments=[], participation=participation, estimated_cost_cny=estimated,
        member_budgets=per_member, unknowns=result.unknowns,
        impact={
            "changed_activity_ids": [item["id"] for item in items],
            "affected_member_ids": sorted({value for item in items for value in item["member_ids"]}),
            "required_member_ids": [str(item.id) for item in members],
            "changed_commitment_ids": [],
            "cost_delta_cny": None, "time_delta_minutes": None,
            "unknowns": result.unknowns, "issues": issues,
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
    job.outcome = outcome
    job.stage = "finished"
    job.result_version_id = version.id
    job.progress_message = ("候选已生成，等待成员确认" if outcome == "feasible"
                            else "候选已生成，但存在需要解决的问题")
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


def _issue(code: str, message: str, severity: str, *, member_ids=None,
           activity_ids=None, options=None) -> dict:
    return {"code": code, "message": message, "severity": severity,
            "member_ids": [str(value) for value in (member_ids or [])],
            "activity_ids": [str(value) for value in (activity_ids or [])],
            "adjustment_options": options or []}


def plan_issues(result: SolveResult, context) -> list[dict]:
    """Turn a solve result into the contract's issue list."""
    issues: list[dict] = []
    for item in result.excluded:
        issues.append(_issue(
            item.code, item.message, "error" if item.blocking else "warning",
            member_ids=item.member_ids, activity_ids=[item.slot.activity_id],
            options=["relax", "split", "defer"] if item.blocking else ["defer"]))
    for slot in result.unplaced:
        issues.append(_issue(
            "ACTIVITY_UNPLACED", f"{slot.name} 在可用时间窗内排不下，请调整时间窗或时长",
            "warning", activity_ids=[slot.activity_id], options=["resize", "defer", "skip"]))
    for member in context.members:
        if not member.has_participation:
            issues.append(_issue(
                "PARTICIPATION_MISSING", "参与区间未填写，暂按整段可用处理", "warning",
                member_ids=[member.member_id], options=["confirm_plan"]))
    return issues


def _outcome(result: SolveResult, issues: list[dict]) -> str:
    if any(item["severity"] == "error" for item in issues):
        return "infeasible"
    if result.data_missing or result.unplaced:
        return "data_missing"
    return "feasible"


def evaluate(version: PlanVersion, context) -> list[dict]:
    """Re-check a stored version against the same constraints the solver used.

    Both `validation` and `publish` call this, so the feasibility gate cannot
    drift away from what the planner actually guaranteed.
    """
    issues: list[dict] = []
    slots = {str(slot.activity_id): slot for slot in context.slots}
    by_member = {member.member_id: member for member in context.members}
    items = activities(version)
    for item in items:
        start = parse_dt(item.get("starts_at"))
        end = parse_dt(item.get("ends_at"))
        if start is None or end is None:
            issues.append(_issue("ACTIVITY_TIME_UNKNOWN", f"{item.get('title', '活动')} 缺少时间",
                                 "error", activity_ids=[item.get("id")]))
            continue
        slot = slots.get(str(item.get("activity_id")))
        for raw in item.get("member_ids", []):
            member = by_member.get(_as_uuid(raw))
            if member is None:
                continue
            if not member.covers(start, end):
                issues.append(_issue(
                    "MEMBER_TIME_CONFLICT",
                    f"{item.get('title', '活动')} 超出成员可参加时间",
                    "error", member_ids=[member.member_id], activity_ids=[item.get("id")],
                    options=["shift", "split", "leave"]))
        if slot is not None:
            if slot.fixed_start is not None and start != slot.fixed_start:
                issues.append(_issue(
                    "RESERVATION_MISMATCH",
                    f"{item.get('title', '活动')} 与预约时间不一致",
                    "error", activity_ids=[item.get("id")], options=["shift", "defer"]))
            if end > slot.latest_end:
                issues.append(_issue(
                    "ACTIVITY_WINDOW_EXCEEDED",
                    f"{item.get('title', '活动')} 超出活动时间窗",
                    "error", activity_ids=[item.get("id")], options=["shift", "resize", "defer"]))
    activity_item_ids = {str(item.get("id")) for item in items if item.get("kind") == "activity"}
    for connection in version.connections or []:
        if connection.get("kind") != "travel":
            continue
        # The synthetic meeting point has no coordinates, so the leg into the
        # first activity carries no real origin. Only inter-activity legs are
        # evidence we are expected to have.
        if str(connection.get("from_id")) not in activity_item_ids:
            continue
        if connection.get("travel_minutes") is None:
            issues.append(_issue(
                "TRAVEL_TIME_UNKNOWN", "缺少坐标，无法估算两点交通时间", "error",
                activity_ids=[connection.get("to_id")], options=["defer", "replace"]))
    # Re-run the solver against the stored activity set. If it cannot place an
    # activity that the version claims to contain, validation must say so
    # instead of reporting a plan as feasible that the planner could not build.
    if context.slots:
        replay = solve(context)
        for excluded in replay.excluded:
            issues.append(_issue(
                excluded.code, excluded.message,
                "error" if excluded.blocking else "warning",
                member_ids=excluded.member_ids, activity_ids=[excluded.slot.activity_id],
                options=["relax", "split", "defer"] if excluded.blocking else ["defer"]))
        for slot in replay.unplaced:
            issues.append(_issue(
                "ACTIVITY_UNPLACED", f"{slot.name} 在可用时间窗内排不下，请调整时间窗或时长",
                "error", activity_ids=[slot.activity_id], options=["resize", "defer", "skip"]))
    total = 0.0
    for item in items:
        if item.get("kind") != "activity":
            continue
        slot = slots.get(str(item.get("activity_id")))
        if slot is None:
            continue
        people = max(len(item.get("member_ids", [])), 1)
        total += slot.cost_cny * people if slot.cost_scope == "per_person" else slot.cost_cny
        for raw in item.get("member_ids", []):
            member = by_member.get(_as_uuid(raw))
            if member is None or member.budget_cny is None:
                continue
            share = slot.cost_cny if slot.cost_scope == "per_person" else slot.cost_cny / people
            if share > member.budget_cny:
                issues.append(_issue(
                    "BUDGET_EXCEEDED",
                    f"「{item.get('title', '活动')}」单项 {int(share)} 元超出成员人均预算 {int(member.budget_cny)} 元",
                    "error", member_ids=[member.member_id], activity_ids=[item.get("id")],
                    options=["relax", "replace", "skip"]))
    return issues


def _as_uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def validation(session: Session, version: PlanVersion) -> PlanValidationOut:
    conflicts = list(session.scalars(select(Conflict).where(
        Conflict.room_id == version.room_id, Conflict.status == "open")).all())
    issues = [item.model_dump(mode="json") for item in issues_from_conflicts(conflicts)]
    high = any(item["severity"] == "error" for item in issues)

    activity_ids = []
    for item in version.activities or []:
        parsed = _as_uuid(item.get("activity_id"))
        if parsed is not None:
            activity_ids.append(parsed)
    room = session.get(Room, version.room_id)
    data_missing = False
    if room is not None:
        facts = list(session.scalars(select(ActivityFact).where(
            ActivityFact.room_id == version.room_id,
            ActivityFact.id.in_(activity_ids))).all()) if activity_ids else []
        context = build_context(session, room, facts)
        issues.extend(evaluate(version, context))
        data_missing = context.data_missing
        for member in context.members:
            if not member.has_participation:
                issues.append(_issue(
                    "PARTICIPATION_MISSING", "参与区间未填写，暂按整段可用处理", "warning",
                    member_ids=[member.member_id], options=["confirm_plan"]))
    errors = any(item["severity"] == "error" for item in issues)
    if errors or high:
        outcome = "infeasible"
    elif data_missing or not version.activities:
        outcome = "unknown" if not version.activities else "data_missing"
    else:
        outcome = "feasible"
    return PlanValidationOut(version_id=version.id, outcome=outcome, issues=issues)


def publish(session: Session, room: Room, version: PlanVersion, actor: Member) -> PlanVersion:
    if version.room_id != room.id:
        raise ApiError(404, "VERSION_NOT_FOUND", "行程版本不存在")
    if version.status not in {"awaiting_confirmation", "draft"}:
        raise ApiError(409, "VERSION_NOT_PUBLISHABLE", "当前版本状态不能发布")
    pending = [item for item in (version.approvals or []) if item.get("decision") == "pending"]
    rejected = [item for item in (version.approvals or []) if item.get("decision") in {"reject", "request_changes"}]
    if pending or rejected:
        raise ApiError(409, "CONFIRMATION_INCOMPLETE", "仍有成员未确认或要求修改")
    check = validation(session, version)
    if check.outcome == "infeasible":
        reasons = list(dict.fromkeys(
            issue["message"] for issue in check.issues if issue.get("severity") == "error"))
        detail = "；".join(reasons)[:240]
        message = (f"存在未解决的高优先级冲突，暂不能发布：{detail}。请先解决冲突再发布"
                   if detail else "行程校验未通过，暂不能发布")
        raise ApiError(409, "PLAN_INFEASIBLE", message)
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
