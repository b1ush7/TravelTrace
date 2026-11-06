from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    field: str
    reason: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def error_response(request: Request, status: int, code: str, message: str, details=None):
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(status_code=status, headers=headers, content={
        "code": code, "message": message, "request_id": request.state.request_id,
        "details": details or [],
    })


async def api_error_handler(request: Request, exc: ApiError):
    return error_response(request, exc.status, exc.code, exc.message)


async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Do not echo passwords or tokens from invalid input.
    details = [{"field": ".".join(map(str, e["loc"])), "reason": e["type"]} for e in exc.errors()]
    return error_response(request, 422, "VALIDATION_ERROR", "请求字段不符合要求", details)


async def database_error_handler(request: Request, exc):
    # Driver errors may contain connection details or SQL parameters.
    return error_response(request, 503, "DATABASE_UNAVAILABLE", "数据库暂时不可用，请稍后重试")
