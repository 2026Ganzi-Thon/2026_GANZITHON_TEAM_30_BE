import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app")

ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    502: "UPSTREAM_ERROR",
}

INTERNAL_MESSAGE = "일시적인 오류가 발생했어요. 잠시 뒤 다시 시도해 주세요"


def error_code(status_code: int, detail) -> str:
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        return detail["code"]
    return ERROR_CODES.get(status_code, "ERROR")


async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        {"detail": exc.detail, "code": error_code(exc.status_code, exc.detail)},
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
        for e in exc.errors()
    ]
    return JSONResponse({"detail": errors, "code": "VALIDATION_ERROR"}, status_code=422)


async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": INTERNAL_MESSAGE, "code": "INTERNAL_ERROR"}, status_code=500)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, unhandled_error)
