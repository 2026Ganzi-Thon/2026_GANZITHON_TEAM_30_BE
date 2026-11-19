"""FastAPI 앱 진입점. 실행: uvicorn app.main:app --reload"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401
from app.ai import models as ai_models  # noqa: F401
from app.config import CORS_ALLOWS_ANY, CORS_ORIGINS, ENV
from app.database import Base, SessionLocal, engine, upgrade_schema
from app.errors import register_error_handlers
from app.middleware import register_middleware
from app.queries import ensure_islands, purge_expired
from app.routers import admin, auth, insights, islands, notifications, post_write, posts, safety, search, stats, users

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    upgrade_schema()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_islands(db)
        purge_expired(db)
    if ENV == "production" and CORS_ALLOWS_ANY:
        log.warning("CORS_ORIGINS is '*' in production. Set it to the FE origin.")
    yield


app = FastAPI(title="간지톤 30팀 API", lifespan=lifespan)

register_error_handlers(app)
register_middleware(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Retry-After"],
    max_age=600,
)

app.include_router(auth.router)
app.include_router(islands.router)
app.include_router(users.router)
app.include_router(posts.router)
app.include_router(post_write.router)
app.include_router(search.router)
app.include_router(notifications.router)
app.include_router(safety.router)
app.include_router(stats.router)
app.include_router(insights.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}
