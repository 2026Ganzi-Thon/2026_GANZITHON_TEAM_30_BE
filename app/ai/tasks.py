"""게시 후 백그라운드 작업 (B 담당): 검사 → 저장 → [여기] 임베딩 → AI 첫 댓글.
FastAPI BackgroundTasks로 응답을 먼저 돌려준 뒤 실행되므로, 요청의 DB 세션 대신 새 세션을 연다."""
import logging

from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, func, or_, select

from app import config
from app.ai.client import AIUnavailable
from app.ai.comment import write_first_comment, write_follow_up
from app.ai.embedding import delete_post_embedding, post_text, upsert_post_embedding
from app.ai.search import search_similar_scored
from app.database import SessionLocal
from app.models import Comment, Notification, Post, User
from app.queries import add_ai_comment, blocked_user_ids

log = logging.getLogger("app.ai")


def _is_public(post: Post) -> bool:
    return post.visibility == "public" and post.status == "published"


def sync_post(post_id: int, *, reembed: bool = True, crisis: bool | None = None) -> None:
    """글 저장·수정 뒤 호출. 공개 글이면 벡터를 저장하고 AI 첫 댓글이 없으면 단다.
    나만 보기 글이면 벡터를 지우고 AI 댓글은 달지 않는다 (분담표 3단계 기준).
    어떤 단계가 실패해도 글 자체에는 영향이 없다."""
    try:
        with SessionLocal() as db:
            post = db.get(Post, post_id)
            if post is None:
                return
            if not _is_public(post):
                delete_post_embedding(db, post.id)
                return

            if reembed:
                upsert_post_embedding(db, post)

            has_ai = db.scalar(select(exists().where(
                Comment.post_id == post.id, Comment.is_ai.is_(True), Comment.parent_id.is_(None)
            )))
            if not has_ai:
                text = write_first_comment(post, crisis=crisis)
                db.refresh(post)  # 댓글을 쓰는 사이 삭제·비공개 전환됐을 수 있다
                if _is_public(post):
                    add_ai_comment(db, post, text)
                    invite_similar_neighbors(db, post)
    except Exception:  # 백그라운드 작업이 서버 로그만 남기고 조용히 끝나게
        log.exception("post %s 백그라운드 AI 작업 실패", post_id)


def _thread(db, root: Comment) -> list[Comment]:
    return list(db.scalars(
        select(Comment)
        .where(
            or_(Comment.id == root.id, Comment.parent_id == root.id),
            Comment.deleted_at.is_(None),
            Comment.hidden_at.is_(None),
        )
        .order_by(Comment.id)
    ))


def _first_neighbor_comment_id(db, post: Post) -> int | None:
    return db.scalar(
        select(func.min(Comment.id)).where(
            Comment.post_id == post.id,
            Comment.is_ai.is_(False),
            Comment.user_id != post.user_id,
            Comment.deleted_at.is_(None),
            Comment.hidden_at.is_(None),
        )
    )


def _ai_replies_today(db, author_id: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    return db.scalar(
        select(func.count()).select_from(Comment).join(Post, Post.id == Comment.post_id).where(
            Post.user_id == author_id,
            Comment.is_ai.is_(True),
            Comment.parent_id.is_not(None),
            Comment.created_at >= since,
        )
    ) or 0


def follow_up_plan(db, post: Post, root: Comment) -> tuple[bool, bool, int]:
    if not root.is_ai or root.parent_id is not None:
        return False, False, 0
    ai_replies = db.scalars(
        select(Comment.id).where(Comment.parent_id == root.id, Comment.is_ai.is_(True))
    ).all()
    if len(ai_replies) >= config.AI_FOLLOWUP_MAX:
        return False, False, 0
    if _ai_replies_today(db, post.user_id) >= config.AI_DAILY_REPLY_LIMIT:
        return False, False, 0
    neighbor_id = _first_neighbor_comment_id(db, post)
    if neighbor_id is not None and any(ai_id > neighbor_id for ai_id in ai_replies):
        return False, False, 0
    neighbors = 1 if neighbor_id is not None else 0
    last_turn = neighbors > 0 or len(ai_replies) + 1 >= config.AI_FOLLOWUP_MAX
    return True, last_turn, neighbors


def reply_in_thread(post_id: int, root_id: int, *, crisis: bool | None = None) -> None:
    try:
        with SessionLocal() as db:
            post = db.get(Post, post_id)
            root = db.get(Comment, root_id)
            if post is None or root is None or not _is_public(post):
                return
            writer = db.get(User, post.user_id)
            if writer is None or writer.deleted_at is not None:
                return

            allowed, last_turn, neighbors = follow_up_plan(db, post, root)
            if not allowed:
                return
            thread = _thread(db, root)
            author_positions = [i for i, c in enumerate(thread) if c.user_id == post.user_id]
            if not author_positions or any(c.is_ai for c in thread[author_positions[-1] + 1:]):
                return

            history = [("온도" if c.is_ai else "작성자", c.content) for c in thread if c.is_ai or c.user_id == post.user_id]
            text = write_follow_up(post, history, last_turn=last_turn, neighbors=neighbors, crisis=crisis)
            db.refresh(post)
            if _is_public(post):
                add_ai_comment(db, post, text, parent_id=root.id)
    except Exception:
        log.exception("post %s AI 이어 답글 실패", post_id)


def invite_similar_neighbors(db, post: Post) -> list[int]:
    if config.INVITE_MAX_PER_POST <= 0:
        return []
    excluded = blocked_user_ids(db, post.user_id) | {post.user_id}
    try:
        scored = search_similar_scored(db, post_text(post), post.island_id, exclude_user_ids=excluded, limit=20)
    except AIUnavailable:
        return []

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    invited: list[int] = []
    for similar_id, _ in scored:
        similar = db.get(Post, similar_id)
        if similar is None or similar.id == post.id or similar.user_id in invited:
            continue
        neighbor = db.get(User, similar.user_id)
        if neighbor is None or neighbor.deleted_at is not None or not neighbor.accept_invites:
            continue
        recent = db.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == neighbor.id,
                Notification.type == "invite",
                Notification.created_at >= since,
            )
        ) or 0
        if recent >= config.INVITE_DAILY_PER_USER:
            continue
        db.add(Notification(user_id=neighbor.id, type="invite", post_id=post.id, actor_id=None))
        invited.append(neighbor.id)
        if len(invited) >= config.INVITE_MAX_PER_POST:
            break
    db.commit()
    return invited
