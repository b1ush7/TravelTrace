from __future__ import annotations

import base64
import hashlib
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Member, PlanNotification, PlanVersion, PushSubscription, Room, utcnow
from app.modules.plans.service import activities, current_published, next_meeting, parse_dt
from app.modules.reach.schemas import LiveAction, LivePrivacy, LiveState, NextMeeting, TravelCard


def mask_token(token: str) -> str:
    return token[:4] + "****" + token[-4:] if len(token) >= 8 else "****"


def encrypt_token(token: str, secret: str) -> str:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key).encrypt(token.encode()).decode()


def _deep_link(room_id: UUID, suffix: str = "") -> str:
    base = f"traveltrace://room/{room_id}"
    return base + (f"/{suffix}" if suffix else "")


def pending_for_member(version: PlanVersion | None, member_id: UUID) -> int:
    if version is None:
        return 0
    return sum(1 for item in (version.approvals or [])
               if str(item.get("member_id")) == str(member_id) and item.get("decision") == "pending")


def build_live_state(room: Room, version: PlanVersion, member: Member,
                     now: datetime | None = None) -> LiveState:
    now = now or datetime.now(timezone.utc)
    items = activities(version)
    pending = pending_for_member(version, member.id)
    actions = [LiveAction(action="open", label="查看行程", deep_link=_deep_link(room.id))]
    if pending:
        actions.append(LiveAction(action="confirm", label="去确认", deep_link=_deep_link(room.id, "confirm")))

    def state(stage, title, subtitle, countdown, progress=None, extra_actions=None):
        merged = actions + (extra_actions or [])
        return LiveState(room_id=room.id, version_id=version.id, stage=stage, title=title,
                         subtitle=subtitle, countdown_to=countdown, progress=progress, actions=merged,
                         privacy=LivePrivacy(hide_members=room.hide_members, hide_budget=room.hide_budget),
                         updated_at=now, expires_at=(countdown or now) + timedelta(hours=2))

    if not items:
        return state("before", "行程待完善", f"{room.destination} · {room.start_date}–{room.end_date}", None)

    parsed = [(item, parse_dt(item.get("starts_at")), parse_dt(item.get("ends_at"))) for item in items]
    parsed = [row for row in parsed if row[1] and row[2]]
    if not parsed:
        return state("before", "行程待完善", room.destination, None)
    first_start = parsed[0][1]
    last_end = max(row[2] for row in parsed)

    current = next((row for row in parsed if row[1] <= now <= row[2]), None)
    if current is not None:
        item, start, end = current
        split = next((seg for seg in (version.split_segments or [])
                      if parse_dt(seg.get("meeting_window_start")) and
                      parse_dt(seg["meeting_window_start"]) <= now <= parse_dt(seg.get("meeting_window_end"))), None)
        if split is not None:
            return state("split", f"分头行动中 · {room.name}", "按约定时间在集合点汇合",
                         parse_dt(split.get("meeting_window_start")))
        if item.get("kind") == "meeting":
            return state("meeting", f"{start.strftime('%H:%M')} 在 {item.get('place_name', '')} 集合",
                         room.name, end, None,
                         [LiveAction(action="navigate", label="导航", deep_link=_deep_link(room.id, "nav"))])
        total = (end - start).total_seconds()
        progress = max(0.0, min(1.0, (now - start).total_seconds() / total)) if total > 0 else None
        extra = []
        if item.get("place_name"):
            extra.append(LiveAction(action="navigate", label="导航", deep_link=_deep_link(room.id, "nav")))
        return state("activity", item.get("title", "进行中"), item.get("place_name", ""), end, progress, extra)

    if now < first_start:
        days = (first_start.date() - now.date()).days
        title = "今天出发" if days == 0 else ("明天出发" if days == 1 else f"还有 {days} 天出发")
        return state("before", title, f"{room.destination} · {room.start_date}–{room.end_date}", first_start)

    future = next(((item, start, end) for item, start, end in parsed if start > now), None)
    if future is not None:
        item, start, end = future
        if item.get("kind") == "meeting" and start - now <= timedelta(hours=2):
            return state("meeting", f"{start.strftime('%H:%M')} 在 {item.get('place_name', '')} 集合",
                         room.name, start, None,
                         [LiveAction(action="navigate", label="导航", deep_link=_deep_link(room.id, "nav"))])
        return state("traveling", f"下一站：{item.get('title', '行程')}",
                     f"{start.strftime('%H:%M')} · {item.get('place_name', '')}", start)

    if now > last_end:
        return state("ended", "行程已结束", "查看复盘与让步记录", None,
                     None, [LiveAction(action="ack", label="查看复盘", deep_link=_deep_link(room.id, "retrospective"))])

    days = (first_start.date() - now.date()).days
    title = "今天出发" if days == 0 else ("明天出发" if days == 1 else f"还有 {days} 天出发")
    return state("before", title, f"{room.destination} · {room.start_date}–{room.end_date}", first_start)


def travel_cards(session: Session, user_id: UUID, today: date | None = None) -> list[TravelCard]:
    today = today or date.today()
    rooms = session.scalars(select(Room).join(Member, Member.room_id == Room.id)
                            .where(Member.user_id == user_id, Member.status == "active",
                                   Room.status != "archived", Room.end_date >= today)
                            .order_by(Room.start_date, Room.id).limit(10)).all()
    result = []
    for room in rooms:
        member = session.scalar(select(Member).where(Member.room_id == room.id, Member.user_id == user_id,
                                                     Member.status == "active"))
        version = current_published(session, room.id)
        pending_versions = session.scalars(select(PlanVersion).where(
            PlanVersion.room_id == room.id, PlanVersion.status == "awaiting_confirmation")).all()
        pending = sum(pending_for_member(item, member.id) for item in pending_versions)
        meeting = next_meeting(version)
        days = (room.start_date - today).days
        result.append(TravelCard(
            room_id=room.id, room_name=room.name, destination=room.destination,
            theme_code=room.theme_code, days_to_start=days if days > 0 else None,
            start_date=room.start_date, end_date=room.end_date, pending_confirmations=pending,
            next_meeting=NextMeeting(title=meeting["title"], place_name=meeting["place_name"],
                                     at=meeting["at"]) if meeting else None,
            current_version_id=version.id if version else None,
            deep_link=_deep_link(room.id), updated_at=room.updated_at,
        ))
    return result


def notifications_for(session: Session, room_id: UUID, member_id: UUID) -> list[PlanNotification]:
    return list(session.scalars(select(PlanNotification).where(
        PlanNotification.room_id == room_id, PlanNotification.member_id == member_id)
        .order_by(PlanNotification.created_at.desc(), PlanNotification.id).limit(50)).all())


def notify_publish(session: Session, room: Room, version: PlanVersion) -> None:
    members = session.scalars(select(Member).where(Member.room_id == room.id,
                                                   Member.status == "active")).all()
    for member in members:
        session.execute(
            PlanNotification.__table__.update().where(
                PlanNotification.room_id == room.id, PlanNotification.member_id == member.id,
                PlanNotification.superseded.is_(False),
            ).values(superseded=True)
        )
        session.add(PlanNotification(
            room_id=room.id, member_id=member.id, version_id=version.id, kind="change_published",
            channel="in_app", delivery_status="sent", deep_link=_deep_link(room.id),
        ))