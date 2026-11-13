from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import ChatImport, Job, Member, Room, User, utcnow
from app.db.session import get_session
from app.modules.imports.schemas import ChatImportIn, ChatImportResult, DeletedResult, ExtractionRequest, JobOut
from app.modules.rooms.service import check_room_version, ensure_writable, lock_room, require_member

router = APIRouter(tags=["讨论与导入"])


def job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id, room_id=job.room_id, kind=job.kind, status=job.status,
        result_version_id=job.result_version_id, error=None, created_at=job.created_at,
        result_version_ids=[job.result_version_id] if job.result_version_id else [],
        planning_outcome=job.outcome, input_room_version=(job.input or {}).get("expected_room_version"),
        stage=job.stage, progress_message=job.progress_message,
    )


@router.post("/rooms/{room_id}/chat-imports", response_model=ChatImportResult, status_code=202,
             summary="提交经授权的聊天片段并异步提取")
def create_import(room_id: UUID, body: ChatImportIn, user: User = Depends(current_user),
                  session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = session.get(Room, room_id)
    ensure_writable(room)
    record = ChatImport(room_id=room_id, member_id=member.id, text=body.text,
                        consent_confirmed=body.consent_confirmed, retention=body.retention,
                        raw_status="pending")
    session.add(record)
    session.flush()
    job = Job(room_id=room_id, kind="extract", status="succeeded", stage="finished",
              outcome="unknown", progress_message="已记录；提取模型尚未接入，未生成需求",
              input={"import_id": str(record.id)})
    session.add(job)
    session.flush()
    record.job_id = job.id
    # The demo extractor is synchronous: discard mode never leaves raw text at rest.
    if body.retention == "discard_after_extraction":
        record.text = ""
        record.raw_status = "deleted"
    else:
        record.raw_status = "retained"
    session.commit()
    return ChatImportResult(import_id=record.id, job_id=job.id, retention=record.retention,
                            raw_status=record.raw_status)


@router.delete("/rooms/{room_id}/chat-imports/{import_id}", response_model=DeletedResult,
               summary="删除导入的聊天原文")
def delete_import(room_id: UUID, import_id: UUID, user: User = Depends(current_user),
                  session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    record = session.get(ChatImport, import_id)
    if record is None or record.room_id != room_id:
        raise ApiError(404, "IMPORT_NOT_FOUND", "导入记录不存在")
    if member.role != "owner" and record.member_id != member.id:
        raise ApiError(403, "NOT_IMPORT_OWNER", "只能删除本人的导入")
    record.text = ""
    record.raw_status = "deleted"
    session.commit()
    return DeletedResult(deleted=True)


@router.post("/rooms/{room_id}/extraction-jobs", response_model=JobOut, status_code=202,
             summary="手动发起房间消息需求提取")
def extraction(room_id: UUID, body: ExtractionRequest, user: User = Depends(current_user),
               session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = lock_room(session, room_id)
    ensure_writable(room)
    check_room_version(room, body.expected_room_version)
    job = Job(room_id=room_id, kind="extract", status="succeeded", stage="finished",
              outcome="unknown", progress_message="提取模型尚未接入，未生成需求",
              input={"message_ids": [str(item) for item in (body.message_ids or [])]})
    session.add(job)
    session.commit()
    return job_out(job)