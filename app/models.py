from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """모든 시각을 UTC로 저장하고, 꺼낼 때 시간대(+00:00)를 붙여 준다.
    SQLite는 시간대를 버리고 저장하기 때문에 그냥 두면 응답이 "2026-11-17T01:55:48"처럼 나가고,
    FE의 new Date()가 이걸 한국 시간으로 읽어 9시간이 어긋난다."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        # 저장할 때: 시간대가 있으면 UTC로 바꾸고, 없으면 UTC로 간주
        if value is not None:
            value = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        # 꺼낼 때: SQLite처럼 시간대 없이 돌아오면 UTC를 붙임
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    job: Mapped[str] = mapped_column(String(50))  
    years: Mapped[str | None] = mapped_column(String(20), nullable=True) 
    nickname: Mapped[str] = mapped_column(String(50), unique=True) 
    character: Mapped[str] = mapped_column(String(30)) 
    privacy_agreed_at: Mapped[datetime] = mapped_column(UTCDateTime()) 
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, default=None)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Island(Base):
    """섬: 통합섬 1개 + 직무별 섬. 서버 시작 시 시드로 만들어 둔다."""

    __tablename__ = "islands"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(10))  # "common"(통합섬) / "job"(직무섬)
    job: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True) 
    name: Mapped[str] = mapped_column(String(50))  


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    island_id: Mapped[int] = mapped_column(ForeignKey("islands.id"), index=True)
    topic: Mapped[str] = mapped_column(String(30)) 
    title: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    comfort_type: Mapped[str] = mapped_column(String(20)) 
    visibility: Mapped[str] = mapped_column(String(10), default="public")  
    show_years: Mapped[bool] = mapped_column(Boolean, default=False)  
    status: Mapped[str] = mapped_column(String(10), default="pending")  
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, onupdate=_now)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)  # AI 댓글은 None
    content: Mapped[str] = mapped_column(Text)
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    # 삭제해도 행은 남겨서 그 자리에 "삭제된 댓글입니다"를 보여 준다 (대댓글 흐름이 끊기지 않게)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, default=None)


class Reaction(Base):
    """공감. 한 사람이 한 글에 한 번만 → (post_id, user_id) 조합을 unique로."""

    __tablename__ = "reactions"
    __table_args__ = (UniqueConstraint("post_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True) 
    type: Mapped[str] = mapped_column(String(10))  
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # AI면 None
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("reporter_id", "target_type", "target_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    target_type: Mapped[str] = mapped_column(String(10))  
    target_id: Mapped[int] = mapped_column()
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("blocker_id", "blocked_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    blocker_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)  # 차단한 사람
    blocked_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)  # 차단당한 사람
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class EmailCode(Base):
    """이메일 인증코드. 코드 원문은 저장하지 않고 해시만 저장한다."""

    __tablename__ = "email_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    purpose: Mapped[str] = mapped_column(String(10))  # signup / login
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(default=0)  # 틀린 횟수
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
