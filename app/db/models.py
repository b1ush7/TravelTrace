from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, Date, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import UTCDateTime


def utcnow():
    return datetime.now(timezone.utc)


METADATA_ARGS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


class Base(DeclarativeBase):
    __table_args__ = METADATA_ARGS


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(255))
    interest_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    interests_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="room_dates_order"),
        METADATA_ARGS,
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(80))
    destination: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="collecting")
    theme_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seed_interest_tag_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    time_zone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    hide_members: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hide_budget: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    window_starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    window_ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    @property
    def interest_summary(self) -> dict:
        # Populated by rooms.service.present_room; defaults keep old callers valid.
        return getattr(self, "_interest_summary", {"common_count": 0, "conflict_count": 0})


class Member(Base):
    __tablename__ = "room_members"
    __table_args__ = (UniqueConstraint("room_id", "user_id", name="uq_room_user"), METADATA_ARGS)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    display_name: Mapped[str] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active")
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Message(Base):
    __tablename__ = "messages"
    sequence: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    id: Mapped[UUID] = mapped_column(Uuid, unique=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    author_member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class MemberInterest(Base):
    __tablename__ = "member_interests"
    __table_args__ = (UniqueConstraint("user_id", "tag_code", name="uq_member_interest_tag"), METADATA_ARGS)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    tag_code: Mapped[str] = mapped_column(String(64))
    strength: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    visibility: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Participation(Base):
    __tablename__ = "participations"
    __table_args__ = (UniqueConstraint("room_id", "member_id", name="uq_participation_member"), METADATA_ARGS)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"), index=True)
    joins_at: Mapped[datetime] = mapped_column(UTCDateTime())
    leaves_at: Mapped[datetime] = mapped_column(UTCDateTime())
    allow_solo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    subject_member_id: Mapped[UUID | None] = mapped_column(ForeignKey("room_members.id"), nullable=True)
    speaker_member_id: Mapped[UUID | None] = mapped_column(ForeignKey("room_members.id"), nullable=True)
    field: Mapped[str] = mapped_column(String(32))
    value: Mapped[dict] = mapped_column(JSON)
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    polarity: Mapped[str] = mapped_column(String(16), default="unknown")
    strength: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    source_message_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Conflict(Base):
    __tablename__ = "conflicts"
    __table_args__ = (UniqueConstraint("room_id", "dedupe_key", name="uq_conflict_dedupe"), METADATA_ARGS)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(Text)
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    affected_member_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="open")
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    key_member_ids: Mapped[list] = mapped_column(JSON, default=list)
    resolution_count: Mapped[int] = mapped_column(Integer, default=0)
    dedupe_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ConflictOption(Base):
    __tablename__ = "conflict_options"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conflict_id: Mapped[UUID] = mapped_column(ForeignKey("conflicts.id"), index=True)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    action: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    affected_member_ids: Mapped[list] = mapped_column(JSON, default=list)
    required_member_ids: Mapped[list] = mapped_column(JSON, default=list)
    cost: Mapped[dict] = mapped_column(JSON, default=dict)
    feasibility: Mapped[str] = mapped_column(String(16), default="feasible")
    rank: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ConflictAction(Base):
    __tablename__ = "conflict_actions"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    conflict_id: Mapped[UUID] = mapped_column(ForeignKey("conflicts.id"), index=True)
    option_id: Mapped[UUID] = mapped_column(ForeignKey("conflict_options.id"))
    member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"))
    action: Mapped[str] = mapped_column(String(16))
    effect: Mapped[str] = mapped_column(String(24))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ActivityFact(Base):
    __tablename__ = "activities"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    owner_member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    place_name: Mapped[str] = mapped_column(String(120))
    place_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    estimated_cost_cny: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_scope: Mapped[str] = mapped_column(String(16), default="per_person")
    window_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reserved_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reservation_status: Mapped[str] = mapped_column(String(24), default="none")
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class PlanVersion(Base):
    __tablename__ = "plan_versions"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    proposer_member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"))
    base_version_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    input_room_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    theme_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activities: Mapped[list] = mapped_column(JSON, default=list)
    connections: Mapped[list] = mapped_column(JSON, default=list)
    split_segments: Mapped[list] = mapped_column(JSON, default=list)
    participation: Mapped[list] = mapped_column(JSON, default=list)
    estimated_cost_cny: Mapped[float | None] = mapped_column(Float, nullable=True)
    member_budgets: Mapped[list] = mapped_column(JSON, default=list)
    unknowns: Mapped[list] = mapped_column(JSON, default=list)
    impact: Mapped[dict] = mapped_column(JSON, default=dict)
    approvals: Mapped[list] = mapped_column(JSON, default=list)
    card_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    progress_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    result_version_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class PlanNotification(Base):
    __tablename__ = "plan_notifications"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"), index=True)
    version_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(16), default="in_app")
    delivery_status: Mapped[str] = mapped_column(String(16), default="sent")
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    acked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    deep_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "device_id", name="uq_push_user_device"), METADATA_ARGS)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str] = mapped_column(String(128))
    platform: Mapped[str] = mapped_column(String(16))
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    app_version: Mapped[str] = mapped_column(String(32))
    push_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    push_token_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Retrospective(Base):
    __tablename__ = "retrospectives"
    __table_args__ = (UniqueConstraint("room_id", name="uq_retrospective_room"), METADATA_ARGS)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    version_id: Mapped[UUID] = mapped_column(Uuid)
    payload: Mapped[dict] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class RoomTemplate(Base):
    __tablename__ = "room_templates"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    source_room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"))
    destination: Mapped[str] = mapped_column(String(100))
    theme_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    days: Mapped[int] = mapped_column(Integer)
    member_count: Mapped[int] = mapped_column(Integer)
    interest_tag_codes: Mapped[list] = mapped_column(JSON, default=list)
    items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
class ShareLink(Base):
    __tablename__ = "share_links"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    created_by_member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
class Deal(Base):
    __tablename__ = "deals"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    created_by_member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"))
    title: Mapped[str] = mapped_column(String(120))
    place_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price_cny: Mapped[float | None] = mapped_column(Float, nullable=True)
    people_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="user")
    verification_status: Mapped[str] = mapped_column(String(16), default="unverified")
    confirmed_by: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ChatImport(Base):
    __tablename__ = "chat_imports"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"))
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    retention: Mapped[str] = mapped_column(String(32))
    job_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    raw_status: Mapped[str] = mapped_column(String(16), default="retained")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    conflict_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"))
    title: Mapped[str] = mapped_column(String(200))
    options: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="open")
    votes: Mapped[list] = mapped_column(JSON, default=list)
    pending_member_ids: Mapped[list] = mapped_column(JSON, default=list)
    affected_hard_constraint_member_ids: Mapped[list] = mapped_column(JSON, default=list)
    eligible_member_ids: Mapped[list] = mapped_column(JSON, default=list)
    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    input_room_version: Mapped[int] = mapped_column(Integer, default=1)
    decision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    outcome_rule: Mapped[str] = mapped_column(String(32), default="absolute_majority")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = METADATA_ARGS
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    proposal_id: Mapped[UUID] = mapped_column(Uuid)
    selected_option_id: Mapped[UUID] = mapped_column(Uuid)
    room_version: Mapped[int] = mapped_column(Integer)
    effect: Mapped[str] = mapped_column(String(32))
    pending_member_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ExecutionRecord(Base):
    __tablename__ = "execution_records"
    __table_args__ = (UniqueConstraint("version_id", "activity_id", "member_id", name="uq_execution_activity_member"), METADATA_ARGS)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    version_id: Mapped[UUID] = mapped_column(Uuid)
    activity_id: Mapped[UUID] = mapped_column(Uuid)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("room_members.id"))
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)