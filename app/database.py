from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    """모든 테이블 모델의 부모 클래스."""


def upgrade_schema() -> None:
    """create_all은 이미 있는 테이블에 컬럼을 더하거나 빼지 않는다.
    기존 DB(팀원 로컬·배포 서버)를 지우지 않고 이번 변경만 반영한다."""
    tables = inspect(engine).get_table_names()
    with engine.begin() as conn:
        if "users" in tables:
            user_cols = {c["name"] for c in inspect(engine).get_columns("users")}
            if "password_hash" in user_cols:  # 비밀번호 로그인 제거
                conn.execute(text("ALTER TABLE users DROP COLUMN password_hash"))
        if "comments" in tables:
            comment_cols = {c["name"] for c in inspect(engine).get_columns("comments")}
            if "deleted_at" not in comment_cols:  # 댓글 삭제 시 "삭제된 댓글입니다" 표시용
                conn.execute(text("ALTER TABLE comments ADD COLUMN deleted_at TIMESTAMP"))


def get_db():
    """요청 하나마다 DB 세션을 열고, 요청이 끝나면 반드시 닫는다 (FastAPI 의존성)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
