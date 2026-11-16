"""FastAPI 앱 진입점. 실행: uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app import models  
from app.ai import models as ai_models  # noqa: F401  post_embeddings 테이블 (B)
from app.database import Base, SessionLocal, engine
from app.queries import ensure_islands
from app.config import CORS_ORIGINS
from app.routers import auth, islands, notifications, post_write, posts, safety, search, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_islands(db)
    yield


app = FastAPI(title="간지톤 30팀 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(islands.router)
app.include_router(users.router)
app.include_router(posts.router)
app.include_router(post_write.router)
app.include_router(search.router)
app.include_router(notifications.router)
app.include_router(safety.router)


@app.get("/health")
def health():
    return {"status": "ok"}
