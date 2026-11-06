from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.engine import create_database_engine
from app.core.errors import ApiError, ErrorResponse, api_error_handler, validation_error_handler, database_error_handler
from app.modules.auth.router import router as auth_router
from app.modules.discussions.router import router as discussions_router
from app.modules.rooms.router import router as rooms_router


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="旅迹多人旅游规划 API", version="0.4.0", responses={
        code: {"model": ErrorResponse, "description": description} for code, description in {
            400: "请求无效", 401: "未登录或凭证无效", 403: "无权限", 404: "资源不存在",
            409: "状态或唯一性冲突", 422: "字段校验失败", 503: "数据库暂时不可用",
        }.items()
    })
    app.state.settings = settings
    app.state.engine = engine if engine is not None else create_database_engine(settings)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(SQLAlchemyError, database_error_handler)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    for router in (auth_router, rooms_router, discussions_router):
        app.include_router(router, prefix="/api/v1")
    return app
