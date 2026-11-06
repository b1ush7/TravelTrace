from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import User
from app.db.session import get_session

password_hash = PasswordHash.recommended()
dummy_hash = password_hash.hash("not-a-user-password")
bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


def issue_token(request: Request, user_id: UUID) -> tuple[str, int]:
    settings = request.app.state.settings
    seconds = settings.token_minutes * 60
    now = datetime.now(timezone.utc)
    token = jwt.encode({"sub": str(user_id), "iat": now, "exp": now + timedelta(seconds=seconds),
                        "iss": "traveltrace", "aud": "traveltrace-api"},
                       settings.jwt_secret.get_secret_value(), algorithm="HS256")
    return token, seconds


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 session: Session = Depends(get_session)) -> User:
    if credentials is None:
        raise ApiError(401, "UNAUTHENTICATED", "请先登录")
    try:
        payload = jwt.decode(credentials.credentials, request.app.state.settings.jwt_secret.get_secret_value(),
                             algorithms=["HS256"], audience="traveltrace-api", issuer="traveltrace",
                             options={"require": ["sub", "exp", "iat"]})
        user_id = UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise ApiError(401, "INVALID_TOKEN", "登录凭证无效或已过期") from None
    user = session.get(User, user_id)
    if user is None:
        raise ApiError(401, "INVALID_TOKEN", "登录凭证无效或已过期")
    return user
