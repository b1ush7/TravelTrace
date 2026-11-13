from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import Member, MemberInterest, Room, User, utcnow
from app.modules.interests.catalog import TAGS, TAGS_BY_CODE, as_dict
from app.modules.interests.schemas import (
    ClashTag, DomainShare, DriftItem, InterestStatsOut, InterestTagOut,
    MemberInterestOut, MemberInterestProfileOut, RoomInterestOverviewOut, TopTag,
)

VISIBLE = {"public", "room"}


def _out(row: MemberInterest) -> MemberInterestOut:
    return MemberInterestOut(tag_code=row.tag_code, strength=row.strength, role=row.role,
                             visibility=row.visibility, source=row.source)


def profile(session: Session, user: User) -> MemberInterestProfileOut:
    rows = session.scalars(
        select(MemberInterest).where(MemberInterest.user_id == user.id)
        .order_by(MemberInterest.tag_code)
    ).all()
    return MemberInterestProfileOut(
        member_id=user.id,
        interests=[_out(row) for row in rows],
        version=user.interest_version or 0,
        updated_at=user.interests_updated_at or user.created_at,
    )


def replace_interests(session: Session, user: User, body) -> MemberInterestProfileOut:
    codes = [item.tag_code for item in body.interests]
    if len(set(codes)) != len(codes):
        raise ApiError(422, "VALIDATION_ERROR", "兴趣标签不能重复")
    unknown = [code for code in codes if code not in TAGS_BY_CODE]
    if unknown:
        raise ApiError(422, "TAG_UNKNOWN", f"未知标签：{unknown[0]}")
    if len(codes) > 30:
        raise ApiError(422, "TOO_MANY_TAGS", "最多设置 30 个兴趣标签")
    session.scalar(select(User).where(User.id == user.id).with_for_update())
    if body.expected_version != (user.interest_version or 0):
        raise ApiError(409, "VERSION_CONFLICT", "兴趣版本已变化，请刷新后重试")
    session.execute(delete(MemberInterest).where(MemberInterest.user_id == user.id))
    for item in body.interests:
        session.add(MemberInterest(user_id=user.id, tag_code=item.tag_code, strength=item.strength,
                                   role=item.role, visibility=item.visibility, source=item.source))
    user.interest_version = (user.interest_version or 0) + 1
    user.interests_updated_at = utcnow()
    session.commit()
    return profile(session, user)


def stats(session: Session, user: User) -> InterestStatsOut:
    rows = session.scalars(select(MemberInterest).where(MemberInterest.user_id == user.id)).all()
    total = len(rows)
    by_domain: dict[str, int] = defaultdict(int)
    for row in rows:
        tag = TAGS_BY_CODE.get(row.tag_code)
        if tag:
            by_domain[tag.domain] += 1
    domain_rows = [
        DomainShare(domain=domain, count=count, share=round(count / total, 4) if total else 0.0)
        for domain, count in sorted(by_domain.items(), key=lambda item: (-item[1], item[0]))
    ]
    top = sorted(rows, key=lambda row: (-row.strength, row.tag_code))[:5]
    top_tags = [TopTag(tag_code=row.tag_code,
                       name=TAGS_BY_CODE[row.tag_code].name if row.tag_code in TAGS_BY_CODE else row.tag_code,
                       count=row.strength) for row in top]
    # The account-level profile has no trip history yet; an empty drift is the
    # honest answer until the first archived trip exists.
    return InterestStatsOut(total_tags=total, by_domain=domain_rows, top_tags=top_tags, drift=[])


def _member_rows(session: Session, room: Room) -> dict[UUID, dict[str, MemberInterestOut]]:
    members = session.scalars(
        select(Member).where(Member.room_id == room.id, Member.status == "active")
    ).all()
    rows = session.scalars(
        select(MemberInterest).where(MemberInterest.user_id.in_([member.user_id for member in members]))
    ).all() if members else []
    by_user: dict[UUID, dict[str, MemberInterestOut]] = defaultdict(dict)
    for row in rows:
        by_user[row.user_id][row.tag_code] = _out(row)
    # Room-level seed tags belong to the owner and never touch the account profile.
    owner = next((member for member in members if member.role == "owner"), None)
    if owner is not None:
        for code in room.seed_interest_tag_codes or []:
            if code in TAGS_BY_CODE and code not in by_user[owner.user_id]:
                by_user[owner.user_id][code] = MemberInterestOut(
                    tag_code=code, strength=3, role="want", visibility="room", source="self")
    return by_user


def room_overview(session: Session, room: Room) -> RoomInterestOverviewOut:
    members = session.scalars(
        select(Member).where(Member.room_id == room.id, Member.status == "active")
    ).all()
    by_user = _member_rows(session, room)
    visible: dict[UUID, dict[str, MemberInterestOut]] = {}
    private_codes: set[str] = set()
    for member in members:
        tags = {code: item for code, item in by_user.get(member.user_id, {}).items() if item.visibility in VISIBLE}
        if tags:
            visible[member.id] = tags
        private_codes.update(code for code, item in by_user.get(member.user_id, {}).items()
                             if item.visibility == "private")
    filled = len(visible)
    common: list[InterestTagOut] = []
    clash: list[ClashTag] = []
    if filled:
        all_codes = {code for tags in visible.values() for code in tags}
        for code in sorted(all_codes):
            tag = TAGS_BY_CODE.get(code)
            if tag is None:
                continue
            roles = {member_id: tags[code].role for member_id, tags in visible.items() if code in tags}
            if len(roles) == filled and all(role in {"must", "want"} for role in roles.values()):
                common.append(InterestTagOut(**as_dict(tag)))
            must_ids = [member_id for member_id, role in roles.items() if role == "must"]
            avoid_ids = [member_id for member_id, role in roles.items() if role == "avoid"]
            if must_ids and avoid_ids:
                clash.append(ClashTag(tag_code=code, name=tag.name,
                                      must_member_ids=must_ids, avoid_member_ids=avoid_ids))
    return RoomInterestOverviewOut(
        room_id=room.id,
        member_count=len(members),
        filled_member_count=filled,
        common_tags=common,
        clash_tags=clash,
        coverage=round(filled / len(members), 4) if members else 0.0,
        private_excluded=len(private_codes),
    )


def summary_counts(session: Session, room: Room) -> tuple[int, int]:
    overview = room_overview(session, room)
    return len(overview.common_tags), len(overview.clash_tags)


def apply_summary(session: Session, room: Room) -> Room:
    common, clash = summary_counts(session, room)
    room._interest_summary = {"common_count": common, "conflict_count": clash}
    return room


def tags_payload(domain: str | None = None) -> list[InterestTagOut]:
    return [InterestTagOut(**as_dict(tag)) for tag in TAGS if domain is None or tag.domain == domain]
