"""여러 API가 같이 쓰는 공통 쿼리 함수. (B도 import해서 사용)"""
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy import Select, exists, func, or_, select, delete
from sqlalchemy.orm import Session
from app.config import ISLAND_COUNT_DAYS, JOBS
from app.models import Block, Comment, Island, Notification, Post, Reaction, RevokedToken, User


# ---------- 섬 ----------

def ensure_islands(db: Session) -> None:
    """통합섬 1개 + 직무섬(JOBS 개수만큼)이 없으면 만든다. 서버 시작 때 호출."""
    if db.scalar(select(Island.id).where(Island.type == "common")) is None:
        db.add(Island(type="common", job=None, name="통합섬"))
    existing = set(db.scalars(select(Island.job).where(Island.type == "job")))
    for job in JOBS:
        if job not in existing:
            db.add(Island(type="job", job=job, name=f"{job}섬"))
    db.commit()


def get_accessible_island(db: Session, island_id: int, user: User) -> Island:
    island = db.get(Island, island_id)
    if island is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "없는 섬입니다")
    if island.type == "job" and island.job != user.job:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "내 직무섬과 통합섬만 들어갈 수 있습니다")
    return island


# ---------- 공개 글 / 차단 ----------

def public_posts() -> Select:
    return select(Post).where(Post.visibility == "public", Post.status == "published")


def blocked_user_ids(db: Session, me_id: int) -> set[int]:
    """내가 차단한 사람 + 나를 차단한 사람. 서로 안 보이게 양방향으로 처리."""
    i_blocked = select(Block.blocked_id).where(Block.blocker_id == me_id)
    blocked_me = select(Block.blocker_id).where(Block.blocked_id == me_id)
    return set(db.scalars(i_blocked.union(blocked_me)))


# ---------- 섬 화면용 집계 ----------

def island_post_count(db: Session, island_id: int, hidden: set[int]) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=ISLAND_COUNT_DAYS)
    posts = public_posts().where(
        Post.island_id == island_id, Post.created_at >= since, Post.user_id.not_in(hidden)
    )
    stmt = select(func.count()).select_from(posts.subquery())
    return db.scalar(stmt) or 0


def has_unread_comment(db: Session, user_id: int, island_id: int) -> bool:
    stmt = select(
        exists().where(
            Notification.user_id == user_id,
            Notification.type == "comment",
            Notification.is_read.is_(False),
            Notification.post_id == Post.id,
            Post.island_id == island_id,
        )
    )
    return bool(db.scalar(stmt))


# ---------- 알림 ----------

def create_notification(db: Session, *, user_id: int, type: str, post_id: int, actor_id: int | None) -> None:
    """알림 1건 추가. commit은 호출한 쪽(댓글·공감 API)이 한 번에 한다.
    자기 글에 자기가 반응한 경우는 알림을 만들지 않는다."""
    if actor_id is not None and actor_id == user_id:
        return
    db.add(Notification(user_id=user_id, type=type, post_id=post_id, actor_id=actor_id))


def add_ai_comment(db: Session, post: Post, content: str) -> Comment:
    """B가 AI 첫 댓글을 저장할 때 쓰는 함수. 댓글과 글쓴이 알림(actor_id=None)을 함께 저장한다."""
    comment = Comment(post_id=post.id, user_id=None, content=content, is_ai=True)
    db.add(comment)
    create_notification(db, user_id=post.user_id, type="comment", post_id=post.id, actor_id=None)
    db.commit()
    db.refresh(comment)
    return comment


# ---------- 검색 ----------

def keyword_filter(q: str):
    pattern = f"%{q}%"
    return or_(Post.title.like(pattern), Post.content.like(pattern))

# ---------- 탈퇴 ----------

def withdraw_user(db: Session, user: User, token_payload: dict) -> None:
    """개인정보만 지우고 게시글이랑 댓글은 남김"""
    user.email = f'left-{user.id}@deleted.invalid'
    user.nickname = f'left-{user.id}'
    user.years = None
    user.deleted_at = datetime.now(timezone.utc)

    db.execute(delete(Post).where(Post.user_id == user.id, Post.visibility == 'private'))
    db.execute(delete(Reaction).where(Reaction.user_id == user.id))
    db.execute(delete(Notification).where(Notification.user_id == user.id))
    db.execute(delete(Block).where((Block.blocker_id == user.id)|(Block.blocked_id == user.id)))

    db.add(RevokedToken(jti=token_payload['jti'], expires_at=datetime.fromtimestamp(token_payload['exp'], tz=timezone.utc),))
    db.commit()

