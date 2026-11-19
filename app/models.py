from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, TypeDecorator, UniqueConstraint, true
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
    color: Mapped[str] = mapped_column(String(20), default="original", server_default="original")
    privacy_agreed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    accept_invites: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # 직접 고른 대표 칭호 (app/titles.py의 key). 비어 있으면 가장 높은 칭호를 자동으로 보여 줌
    title_key: Mapped[str | None] = mapped_column(String(30), nullable=True, default=None)
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
    # 글을 쓴 지도 위 자리(%). 이 자리에 글쓴이 캐릭터와 글이 놓인다
    map_x: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    map_y: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, onupdate=_now)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)  # AI 댓글은 None
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, default=None, index=True
    )
    content: Mapped[str] = mapped_column(Text)
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    # 삭제해도 행은 남겨서 그 자리에 "삭제된 댓글입니다"를 보여 준다 (대댓글 흐름이 끊기지 않게)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, default=None)
    hidden_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, default=None)
    thanked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, default=None)


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
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, default=None)


class ModerationCase(Base):
    __tablename__ = "moderation_cases"
    __table_args__ = (UniqueConstraint("target_type", "target_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(10))
    target_id: Mapped[int] = mapped_column(index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    state: Mapped[str] = mapped_column(String(10), default="review")
    report_score: Mapped[float] = mapped_column(default=0.0)
    ai_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    restored_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    appeal_reason: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    appealed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, onupdate=_now)


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


class IslandVisit(Base):
    """섬에 다녀간 기록 (발자국). 한 사람·한 섬당 한 줄만 두고, 마지막으로 머문 자리와 시각을 덮어쓴다."""

    __tablename__ = "island_visits"
    __table_args__ = (UniqueConstraint("user_id", "island_id", name="uq_island_visit"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    island_id: Mapped[int] = mapped_column(ForeignKey("islands.id"), index=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    visited_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, index=True)


class PrivateChat(Base):
    """나만 보기 고민에서 작성자와 AI 이웃 '온도'가 나눈 대화. 작성자 말고는 아무도 볼 수 없다.
    댓글(comments)과 따로 두어, 나중에 글을 공개로 바꿔도 이 대화는 이웃에게 보이지 않는다."""

    __tablename__ = "private_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
