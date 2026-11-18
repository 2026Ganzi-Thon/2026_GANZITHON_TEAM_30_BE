from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import config

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

API_ONLY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


def body_too_large(request: Request) -> bool:
    length = request.headers.get("content-length", "")
    return length.isdigit() and int(length) > config.MAX_BODY_BYTES


def register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_guard(request: Request, call_next):
        if body_too_large(request):
            response = JSONResponse(
                {"detail": "요청 본문이 너무 커요", "code": "PAYLOAD_TOO_LARGE"}, status_code=413
            )
        else:
            response = await call_next(request)
        for key, value in BASE_HEADERS.items():
            response.headers.setdefault(key, value)
        if not request.url.path.startswith(DOC_PATHS):
            for key, value in API_ONLY_HEADERS.items():
                response.headers.setdefault(key, value)
        if config.ENV == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
