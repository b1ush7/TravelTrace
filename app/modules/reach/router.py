from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user
from app.db.models import Member, PlanNotification, PushSubscription, Room, User, utcnow
from app.db.session import get_session
from app.modules.plans.service import current_published
from app.modules.reach.schemas import (
    AckResult, LiveState, PlanNotificationOut, PushSubscriptionIn, PushSubscriptionOut, TravelCard,
)
from app.modules.reach.service import (
    build_live_state, encrypt_token, mask_token, notifications_for, travel_cards,
)
from app.modules.rooms.service import require_member

router = APIRouter(tags=["行程执行"])


@router.get("/me/travel-cards", response_model=list[TravelCard], summary="获取负一屏旅行卡片")
def cards(user: User = Depends(current_user), session: Session = Depends(get_session)):
    return travel_cards(session, user.id)


@router.get("/rooms/{room_id}/live-state", response_model=LiveState, summary="获取流体云实时状态")
def live_state(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    room = session.get(Room, room_id)
    version = current_published(session, room.id)
    if version is None:
        raise ApiError(404, "NO_PUBLISHED_VERSION", "房间还没有生效版本")
    return build_live_state(room, version, member)


@router.post("/devices/push-subscriptions", response_model=PushSubscriptionOut,
             summary="注册设备推送与卡片能力")
def register_device(body: PushSubscriptionIn, request: Request, user: User = Depends(current_user),
                    session: Session = Depends(get_session)):
    row = session.scalar(select(PushSubscription).where(
        PushSubscription.user_id == user.id, PushSubscription.device_id == body.device_id))
    secret = request.app.state.settings.jwt_secret.get_secret_value()
    now = utcnow()
    if row is None:
        row = PushSubscription(user_id=user.id, device_id=body.device_id, platform=body.platform,
                               capabilities=body.capabilities, app_version=body.app_version,
                               push_token_encrypted=encrypt_token(body.push_token, secret),
                               push_token_masked=mask_token(body.push_token),
                               created_at=now, last_seen_at=now)
        session.add(row)
    else:
        row.platform = body.platform
        row.capabilities = body.capabilities
        row.app_version = body.app_version
        row.push_token_encrypted = encrypt_token(body.push_token, secret)
        row.push_token_masked = mask_token(body.push_token)
        row.last_seen_at = now
        row.revoked_at = None
    session.commit()
    return PushSubscriptionOut(
        id=row.id, device_id=row.device_id, platform=row.platform, capabilities=row.capabilities,
        app_version=row.app_version, push_token_masked=row.push_token_masked,
        created_at=row.created_at, last_seen_at=row.last_seen_at)


@router.delete("/devices/push-subscriptions/{subscription_id}", status_code=204,
               summary="注销设备推送")
def unregister_device(subscription_id: UUID, user: User = Depends(current_user),
                      session: Session = Depends(get_session)):
    row = session.get(PushSubscription, subscription_id)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "SUBSCRIPTION_NOT_FOUND", "订阅不存在")
    session.delete(row)
    session.commit()
    return Response(status_code=204)


@router.get("/rooms/{room_id}/notifications", response_model=list[PlanNotificationOut],
            summary="查看本人行程变更通知")
def notifications(room_id: UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    return notifications_for(session, room_id, member.id)


@router.post("/rooms/{room_id}/notifications/{notification_id}/ack", response_model=AckResult,
             summary="确认已读通知")
def ack(room_id: UUID, notification_id: UUID, user: User = Depends(current_user),
        session: Session = Depends(get_session)):
    member = require_member(session, room_id, user.id)
    row = session.get(PlanNotification, notification_id)
    if row is None or row.room_id != room_id:
        raise ApiError(404, "NOTIFICATION_NOT_FOUND", "通知不存在")
    if row.member_id != member.id:
        raise ApiError(403, "NOT_NOTIFICATION_RECEIVER", "只能确认本人收到的通知")
    if row.acked_at is None:
        row.acked_at = utcnow()
        session.commit()
    return AckResult(notification_id=row.id, acked_at=row.acked_at)
