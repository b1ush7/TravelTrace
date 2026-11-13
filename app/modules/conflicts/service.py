from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import (
    Claim, Conflict, ConflictAction, ConflictOption, Member, Participation, PlanVersion, Room, utcnow,
)
from app.modules.conflicts.schemas import ConflictOut, PlanIssueOut
from app.modules.interests.service import room_overview
from app.modules.themes import catalog as themes

HARD = "hard"


def _dt(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _member_names(session: Session, room_id: UUID) -> dict[UUID, str]:
    rows = session.scalars(select(Member).where(Member.room_id == room_id, Member.status == "active")).all()
    return {row.id: row.display_name for row in rows}


def _confirmed_hard(session: Session, room_id: UUID) -> list[Claim]:
    return list(session.scalars(select(Claim).where(
        Claim.room_id == room_id, Claim.status == "confirmed", Claim.strength == HARD)).all())


def _budget_spec(session: Session, room: Room, claims: list[Claim], names: dict[UUID, str]) -> dict | None:
    member_count = max(len(names), 1)
    rows = []
    for claim in claims:
        if claim.field != "budget":
            continue
        value = claim.value or {}
        amount = value.get("amount_cny")
        if amount is None:
            continue
        per_person = float(amount) if value.get("scope") != "total" else float(amount) / member_count
        rows.append((claim, per_person))
    if len(rows) < 2:
        return None
    amounts = sorted(item[1] for item in rows)
    difference = amounts[-1] - amounts[0]
    if difference < 300:
        return None
    median = amounts[len(amounts) // 2]
    key_claim, key_amount = max(rows, key=lambda item: abs(item[1] - median))
    detail = "、".join(f"{names.get(c.subject_member_id, '成员')} 人均 {int(v)} 元" for c, v in rows)
    return {
        "type": "budget",
        "description": f"预算口径归一后差异 {int(difference)} 元：{detail}",
        "claim_ids": [str(c.id) for c, _ in rows],
        "affected_member_ids": [str(c.subject_member_id) for c, _ in rows if c.subject_member_id],
        "key_member_ids": [str(key_claim.subject_member_id)] if key_claim.subject_member_id else [],
        "severity": "high" if difference >= 800 else "medium",
        "dedupe_key": "budget:" + ",".join(sorted(str(c.id) for c, _ in rows)),
    }


def _time_spec(session: Session, room: Room, claims: list[Claim], names: dict[UUID, str]) -> dict | None:
    windows = []
    for claim in claims:
        if claim.field not in {"time", "schedule"}:
            continue
        value = claim.value or {}
        start = _dt(value.get("start_time"))
        end = _dt(value.get("end_time"))
        if start and end and start < end and claim.subject_member_id:
            windows.append((claim.subject_member_id, start, end, claim))
    if len(windows) < 2:
        participations = session.scalars(select(Participation).where(Participation.room_id == room.id)).all()
        windows = [(row.member_id, row.joins_at, row.leaves_at, None) for row in participations]
    if len(windows) < 2:
        return None
    for index, first in enumerate(windows):
        for second in windows[index + 1:]:
            if first[1] < second[2] and second[1] < first[2]:
                continue
            width_first = first[2] - first[1]
            width_second = second[2] - second[1]
            key_member = first[0] if width_first <= width_second else second[0]
            claim_ids = [str(item[3].id) for item in (first, second) if item[3] is not None]
            return {
                "type": "time",
                "description": (f"{names.get(first[0], '成员')} 与 {names.get(second[0], '成员')} 的时间窗不重叠，"
                                f"无法同时参加同一段活动"),
                "claim_ids": claim_ids,
                "affected_member_ids": [str(first[0]), str(second[0])],
                "key_member_ids": [str(key_member)],
                "severity": "high",
                "dedupe_key": "time:" + ",".join(sorted(str(first[0]) + str(second[0]) for _ in [0])),
            }
    return None


def _place_spec(claims: list[Claim], names: dict[UUID, str]) -> list[dict]:
    positive: dict[str, list[Claim]] = defaultdict(list)
    negative: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        if claim.field not in {"place", "preference", "interest"}:
            continue
        if claim.polarity not in {"positive", "negative"}:
            continue
        value = claim.value or {}
        key = (value.get("place_id") or value.get("place_name") or value.get("text") or "").strip().lower()
        if not key:
            continue
        (positive if claim.polarity == "positive" else negative)[key].append(claim)
    result = []
    for key in sorted(set(positive) & set(negative)):
        pos, neg = positive[key], negative[key]
        positive_ids = [c.subject_member_id for c in pos if c.subject_member_id]
        negative_ids = [c.subject_member_id for c in neg if c.subject_member_id]
        if not positive_ids or not negative_ids:
            continue
        display = (pos[0].value or {}).get("place_name") or (pos[0].value or {}).get("text") or key
        result.append({
            "type": "place" if pos[0].field == "place" else "other",
            "description": (f"{names.get(positive_ids[0], '成员')} 想去「{display}」，"
                            f"{names.get(negative_ids[0], '成员')} 明确回避"),
            "claim_ids": [str(c.id) for c in pos + neg],
            "affected_member_ids": [str(item) for item in positive_ids + negative_ids],
            "key_member_ids": [str(negative_ids[0])],
            "severity": "high",
            "dedupe_key": "place:" + key,
        })
    return result


def _theme_specs(session: Session, room: Room, names: dict[UUID, str]) -> list[dict]:
    if not room.theme_code or not themes.exists(room.theme_code):
        return []
    result = []
    day = room.start_date
    mondays = []
    while day <= room.end_date:
        if day.weekday() == 0:
            mondays.append(day)
        day += timedelta(days=1)
    if mondays and any(rule["code"] == "RED_MONDAY_CLOSED" for rule in themes.rules(room.theme_code)):
        result.append({
            "type": "other",
            "description": f"行程包含周一（{mondays[0].isoformat()}），{themes.name(room.theme_code)} 多数场馆闭馆",
            "claim_ids": [],
            "affected_member_ids": [str(item) for item in names],
            "key_member_ids": [],
            "severity": "error",
            "dedupe_key": "theme:RED_MONDAY_CLOSED",
        })
    stale = [fact for fact in themes.facts(room.theme_code) if fact["stale"]]
    if stale:
        result.append({
            "type": "other",
            "description": f"主题事实已超过 180 天未核实：{stale[0]['title']}（{stale[0]['place_name']}）",
            "claim_ids": [],
            "affected_member_ids": [str(item) for item in names],
            "key_member_ids": [],
            "severity": "warning",
            "dedupe_key": "theme:STALE_FACT",
        })
    return result


def _interest_specs(session: Session, room: Room) -> list[dict]:
    overview = room_overview(session, room)
    result = []
    for clash in overview.clash_tags:
        result.append({
            "type": "other",
            "description": f"「{clash.name}」雷区：有人必去，有人回避",
            "claim_ids": [],
            "affected_member_ids": [str(item) for item in clash.must_member_ids + clash.avoid_member_ids],
            "key_member_ids": [str(clash.avoid_member_ids[0])],
            "severity": "high",
            "dedupe_key": "interest:" + clash.tag_code,
        })
    return result


def refresh_conflicts(session: Session, room: Room, *, include_theme_rules: bool = True,
                      include_interest_clash: bool = True, bump: bool = False) -> list[Conflict]:
    names = _member_names(session, room.id)
    claims = _confirmed_hard(session, room.id)
    specs = []
    budget = _budget_spec(session, room, claims, names)
    if budget:
        specs.append(budget)
    time_spec = _time_spec(session, room, claims, names)
    if time_spec:
        specs.append(time_spec)
    specs.extend(_place_spec(claims, names))
    if include_theme_rules:
        specs.extend(_theme_specs(session, room, names))
    if include_interest_clash:
        specs.extend(_interest_specs(session, room))

    existing = {row.dedupe_key: row for row in session.scalars(
        select(Conflict).where(Conflict.room_id == room.id)).all()}
    changed = False
    seen = set()
    for spec in specs:
        seen.add(spec["dedupe_key"])
        row = existing.get(spec["dedupe_key"])
        if row is None:
            row = Conflict(room_id=room.id, status="open", resolution_count=0, **{
                key: spec[key] for key in (
                    "type", "description", "claim_ids", "affected_member_ids", "key_member_ids",
                    "severity", "dedupe_key")})
            session.add(row)
            changed = True
        else:
            if row.status != "open":
                row.status = "open"
                changed = True
            row.type = spec["type"]
            row.description = spec["description"]
            row.claim_ids = spec["claim_ids"]
            row.affected_member_ids = spec["affected_member_ids"]
            row.key_member_ids = spec["key_member_ids"]
            row.severity = spec["severity"]
    for key, row in existing.items():
        if key not in seen and row.status == "open":
            row.status = "resolved"
            changed = True
    if changed and bump:
        room.version += 1
        room.updated_at = utcnow()
    session.commit()
    return list(session.scalars(select(Conflict).where(Conflict.room_id == room.id)
                                .order_by(Conflict.created_at, Conflict.id)).all())


def resolve_conflicts_for_read(session: Session, room: Room) -> list[Conflict]:
    rows = list(session.scalars(select(Conflict).where(Conflict.room_id == room.id)
                                .order_by(Conflict.created_at, Conflict.id)).all())
    if not rows:
        rows = refresh_conflicts(session, room, bump=False)
    return rows


def generate_options(session: Session, conflict: Conflict, room: Room) -> list[ConflictOption]:
    existing = list(session.scalars(select(ConflictOption).where(
        ConflictOption.conflict_id == conflict.id).order_by(ConflictOption.rank)).all())
    if existing:
        return existing
    affected = [UUID(str(item)) for item in (conflict.affected_member_ids or [])]
    key = [UUID(str(item)) for item in (conflict.key_member_ids or [])]
    if not affected:
        affected = [row.id for row in session.scalars(
            select(Member).where(Member.room_id == room.id, Member.status == "active")).all()]
    required = key or affected
    names = _member_names(session, room.id)
    who = names.get(key[0], "本人") if key else "本人"
    specs = [
        ("relax", f"让 {who} 放宽条件", "仅调整该成员的硬约束，不改动其他人的安排",
         affected, required, {"time_delta_minutes": 0, "cost_delta_cny": 0, "walking_delta_m": 0}, "feasible"),
        ("replace", "换一个替代方案", "替换活动或地点，保留其他人的行程不变",
         affected, affected, {"time_delta_minutes": 0, "cost_delta_cny": -100, "walking_delta_m": 300}, "feasible"),
        ("shift", "整体顺延 60 分钟", "把冲突活动前后挪动，代价是等待或晚到",
         affected, affected, {"time_delta_minutes": 60, "cost_delta_cny": 0, "walking_delta_m": 0}, "feasible"),
        ("split", "分头行动，按时汇合", "两组各走各的，在一个集合点汇合",
         affected, affected, {"time_delta_minutes": 0, "cost_delta_cny": 40, "walking_delta_m": 600},
         "feasible"),
        ("defer", "保留待定，临期再定", "先不决定，出发前再确认",
         affected, affected, {"time_delta_minutes": 0, "cost_delta_cny": 0, "walking_delta_m": 0}, "needs_data"),
    ]
    if len(names) >= 3:
        specs.append(("vote", "发起投票", "少数服从多数，按确认规则生效",
                      affected, affected, {"time_delta_minutes": 0, "cost_delta_cny": 0, "walking_delta_m": 0},
                      "feasible"))
    if conflict.type == "budget":
        specs[1] = ("replace", "换一个更便宜的替代", "降低预算缺口，代价是体验降级",
                    affected, affected, {"time_delta_minutes": 0, "cost_delta_cny": -200, "walking_delta_m": 0},
                    "feasible")
    options = []
    for rank, (action, title, description, aff, req, cost, feasibility) in enumerate(specs, start=1):
        option = ConflictOption(conflict_id=conflict.id, room_id=room.id, action=action, title=title,
                                description=description, affected_member_ids=[str(item) for item in aff],
                                required_member_ids=[str(item) for item in req], cost=cost,
                                feasibility=feasibility, rank=rank)
        session.add(option)
        options.append(option)
    conflict.resolution_count = len(options)
    session.commit()
    return options


def conflict_out(row: Conflict) -> ConflictOut:
    return ConflictOut(
        id=row.id, type=row.type, description=row.description,
        claim_ids=[UUID(str(item)) for item in (row.claim_ids or [])],
        affected_member_ids=[UUID(str(item)) for item in (row.affected_member_ids or [])],
        status=row.status, severity=row.severity,
        key_member_ids=[UUID(str(item)) for item in (row.key_member_ids or [])],
        resolution_count=row.resolution_count,
    )


def issues_from_conflicts(rows: list[Conflict]) -> list[PlanIssueOut]:
    return [PlanIssueOut(
        code=row.dedupe_key.upper().replace(":", "_"),
        message=row.description,
        severity="error" if row.severity == "error" else "warning",
        member_ids=[UUID(str(item)) for item in (row.affected_member_ids or [])],
        activity_ids=[],
        adjustment_options=["relax", "replace", "shift", "split", "defer"],
    ) for row in rows if row.status == "open"]


def create_pending_version(session: Session, room: Room, conflict: Conflict, option: ConflictOption,
                           member: Member, comment: str | None) -> PlanVersion:
    base = session.scalar(select(PlanVersion).where(
        PlanVersion.room_id == room.id, PlanVersion.status == "published"
    ).order_by(PlanVersion.published_at.desc()))
    participation = [{"member_id": str(row.member_id), "joins_at": row.joins_at.isoformat(),
                      "leaves_at": row.leaves_at.isoformat(), "allow_solo": row.allow_solo,
                      "room_version": room.version}
                     for row in session.scalars(select(Participation).where(
                         Participation.room_id == room.id)).all()]
    required = [UUID(str(item)) for item in (option.required_member_ids or [])]
    cost = option.cost or {}
    version = PlanVersion(
        room_id=room.id,
        proposer_member_id=member.id,
        base_version_id=base.id if base else None,
        input_room_version=room.version,
        status="awaiting_confirmation",
        theme_code=room.theme_code,
        activities=list(base.activities) if base else [],
        connections=list(base.connections) if base else [],
        split_segments=list(base.split_segments) if base else [],
        participation=participation,
        estimated_cost_cny=base.estimated_cost_cny if base else None,
        member_budgets=list(base.member_budgets) if base else [],
        unknowns=list(base.unknowns) if base else [],
        impact={
            "changed_activity_ids": [],
            "affected_member_ids": sorted(option.affected_member_ids),
            "required_member_ids": sorted(option.required_member_ids),
            "changed_commitment_ids": [],
            "cost_delta_cny": cost.get("cost_delta_cny"),
            "time_delta_minutes": cost.get("time_delta_minutes"),
            "unknowns": [] if option.feasibility == "feasible" else ["方案确定性待补充"],
        },
        approvals=[{"member_id": str(item), "decision": "pending", "decided_at": None,
                    "comment": comment or ""} for item in required],
        card_summary={"title": option.title, "subtitle": conflict.description[:80],
                      "at": utcnow().isoformat()},
        expires_at=utcnow() + timedelta(hours=24),
    )
    session.add(version)
    session.commit()
    return version


def apply_relax(session: Session, room: Room, conflict: Conflict, option: ConflictOption,
                member: Member) -> None:
    claim_ids = [UUID(str(item)) for item in (conflict.claim_ids or [])]
    if claim_ids:
        claims = session.scalars(select(Claim).where(Claim.id.in_(claim_ids),
                                                     Claim.subject_member_id == member.id)).all()
        for claim in claims:
            claim.strength = "soft"
            claim.version += 1
    conflict.status = "resolved"
    conflict.updated_at = utcnow()
    session.add(ConflictAction(room_id=room.id, conflict_id=conflict.id, option_id=option.id,
                               member_id=member.id, action=option.action, effect="applied"))
    room.version += 1
    room.updated_at = utcnow()
    session.commit()