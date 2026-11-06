from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import current_user, dummy_hash, issue_token, password_hash
from app.db.models import User
from app.db.session import get_session
from app.modules.auth.schemas import Credentials, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(tags=["用户与身份"])


@router.post("/auth/register", response_model=UserResponse, status_code=201, summary="注册账号")
def register(body: RegisterRequest, session: Session = Depends(get_session)):
    user = User(username=body.username, display_name=body.display_name,
                password_hash=password_hash.hash(body.password.get_secret_value()))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiError(409, "USERNAME_TAKEN", "用户名已被使用") from None
    return user


@router.post("/auth/session", response_model=TokenResponse, summary="用户名密码登录")
def login(body: Credentials, request: Request, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.username == body.username))
    valid = password_hash.verify(body.password.get_secret_value(), user.password_hash if user else dummy_hash)
    if not valid or user is None:
        raise ApiError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
    token, seconds = issue_token(request, user.id)
    return TokenResponse(access_token=token, expires_in=seconds, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse, summary="查询当前用户")
def me(user: User = Depends(current_user)):
    return user
