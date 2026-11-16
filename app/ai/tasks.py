"""게시 후 백그라운드 작업 (B 담당): 검사 → 저장 → [여기] 임베딩 → AI 첫 댓글.
FastAPI BackgroundTasks로 응답을 먼저 돌려준 뒤 실행되므로, 요청의 DB 세션 대신 새 세션을 연다."""
import logging

from sqlalchemy import exists, select

from app.ai.comment import write_first_comment
from app.ai.embedding import delete_post_embedding, upsert_post_embedding
from app.database import SessionLocal
from app.models import Comment, Post
from app.queries import add_ai_comment

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

            has_ai = db.scalar(select(exists().where(Comment.post_id == post.id, Comment.is_ai.is_(True))))
            if not has_ai:
                text = write_first_comment(post, crisis=crisis)
                db.refresh(post)  # 댓글을 쓰는 사이 삭제·비공개 전환됐을 수 있다
                if _is_public(post):
                    add_ai_comment(db, post, text)
    except Exception:  # 백그라운드 작업이 서버 로그만 남기고 조용히 끝나게
        log.exception("post %s 백그라운드 AI 작업 실패", post_id)
