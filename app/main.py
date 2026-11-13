from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.engine import create_database_engine
from app.core.errors import ApiError, ErrorResponse, api_error_handler, validation_error_handler, database_error_handler
from app.modules.auth.router import router as auth_router
from app.modules.claims.router import router as claims_router
from app.modules.deals.router import router as deals_router
from app.modules.conflicts.router import router as conflicts_router
from app.modules.discussions.router import router as discussions_router
from app.modules.imports.router import router as imports_router
from app.modules.interests.router import router as interests_router
from app.modules.places.router import router as places_router
from app.modules.plans.router import router as plans_router
from app.modules.proposals.router import router as proposals_router
from app.modules.reach.router import router as reach_router
from app.modules.retrospectives.router import router as retrospectives_router
from app.modules.sharing.router import router as sharing_router
from app.modules.rooms.router import router as rooms_router
from app.modules.themes.router import router as themes_router


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="旅迹多人旅游规划 API", version="0.6.0", responses={
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

    for router in (auth_router, rooms_router, discussions_router, interests_router, themes_router,
                   claims_router, conflicts_router, plans_router, proposals_router, reach_router,
                   sharing_router, retrospectives_router, deals_router, imports_router, places_router):
        app.include_router(router, prefix="/api/v1")
    return app