from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.ai import CRISIS_SUPPORT, check_text
from app.ai.client import AIUnavailable
from app.ai.embedding import post_text
from app.ai.search import search_similar_scored
from app.ai.tasks import follow_up_plan, reply_in_thread
from app.config import DELETED_COMMENT, HIDDEN_COMMENT
from app.database import get_db
from app.deps import get_current_user
from app.models import Comment, Island, Notification, Post, Reaction, User
from app.queries import (
    blocked_user_ids, create_notification, get_accessible_island, posts_with_neighbor_comment, visible_comment_counts,
)
from app.ratelimit import limit_user
from app.routers.islands import to_author
from app.schemas import (
    CommentCreate, CommentCreateOut, CommentOut, PostDetailOut, ReactionOut, SimilarPostOut, ThanksOut,
)

router = APIRouter(prefix="/posts", tags=["posts"])

def get_visible_post(db: Session, post_id: int, me: User) -> tuple[Post, Island]:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, '고민글을 찾을 수 없습니다.')
    if post.user_id != me.id:
        not_public = post.visibility != 'public' or post.status != 'published'
        if not_public or post.user_id in blocked_user_ids(db,me.id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, '고민글을 찾을 수 없습니다.')
    island = get_accessible_island(db, post.island_id, me)
    return post, island


def ensure_open_for_reaction(post: Post) -> None:
    if post.visibility != "public" or post.status != "published":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "공개된 고민글에만 댓글·공감을 남길 수 있습니다")


def reaction_count(db: Session, post_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Reaction).where(Reaction.post_id == post_id)) or 0


@router.get("/{post_id}", response_model=PostDetailOut)
def get_post_detail(post_id: int, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post, island = get_visible_post(db, post_id, me)
    is_mine = post.user_id == me.id

    db.execute(
        update(Notification)
        .where(Notification.user_id == me.id, Notification.post_id == post.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()

    hidden = blocked_user_ids(db, me.id)
    comments = db.scalars(
        select(Comment)
        .where(Comment.post_id == post.id, or_(Comment.user_id.is_(None), Comment.user_id.not_in(hidden)))
        .order_by(Comment.id)
    ).all()

    user_ids = {c.user_id for c in comments if c.user_id is not None} | {post.user_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
    writer = users[post.user_id]

    return PostDetailOut(
        id=post.id,
        island_id=post.island_id,
        topic=post.topic,
        title=post.title,
        content=post.content,
        comfort_type=post.comfort_type,
        visibility=post.visibility,
        status=post.status,
        created_at=post.created_at,
        updated_at=post.updated_at,
        author=to_author(writer, island),
        years=writer.years if post.show_years and writer.deleted_at is None else None,
        is_mine=is_mine,
        reaction_count=reaction_count(db, post.id),
        reacted_by_me=bool(db.scalar(select(exists().where(Reaction.post_id == post.id, Reaction.user_id == me.id)))),
        comments=[comment_out(c, users, island, me) for c in comments],
    )


def comment_out(c: Comment, users: dict[int, User], island: Island, me: User) -> CommentOut:
    """삭제된 댓글은 자리만 남기고 내용·작성자를 숨긴다."""
    if c.deleted_at is not None:
        return CommentOut(id=c.id, content=DELETED_COMMENT, is_ai=c.is_ai, is_deleted=True, parent_id=c.parent_id,
                          author=None, is_mine=False, created_at=c.created_at)
    if c.hidden_at is not None:
        return CommentOut(id=c.id, content=HIDDEN_COMMENT, is_ai=c.is_ai, is_hidden=True, parent_id=c.parent_id,
                          author=None, is_mine=False, created_at=c.created_at)
    return CommentOut(
        id=c.id,
        content=c.content,
        is_ai=c.is_ai,
        thanked=c.thanked_at is not None,
        parent_id=c.parent_id,
        author=None if c.user_id is None else to_author(users[c.user_id], island),
        is_mine=c.user_id == me.id,
        created_at=c.created_at,
    )


def get_reply_root(db: Session, post: Post, parent_id: int, me: User) -> Comment:
    parent = db.get(Comment, parent_id)
    unavailable = (
        parent is None
        or parent.post_id != post.id
        or parent.deleted_at is not None
        or parent.hidden_at is not None
        or (parent.user_id is not None and parent.user_id in blocked_user_ids(db, me.id))
    )
    if unavailable:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "답글을 달 댓글을 찾을 수 없습니다")
    if parent.parent_id is None:
        return parent
    return db.get(Comment, parent.parent_id) or parent


def wants_ai_reply(db: Session, post: Post, root: Comment | None, me: User) -> bool:
    if root is None or post.user_id != me.id:
        return False
    allowed, _, _ = follow_up_plan(db, post, root)
    return allowed


@router.post(
    "/{post_id}/comments", response_model=CommentCreateOut, status_code=status.HTTP_201_CREATED,
    dependencies=[limit_user("comment", 30, 600)],
)
def create_comment(
    post_id: int,
    body: CommentCreate,
    background: BackgroundTasks,
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post, island = get_visible_post(db, post_id, me)
    ensure_open_for_reaction(post)
    root = get_reply_root(db, post, body.parent_id, me) if body.parent_id is not None else None

    result = check_text(body.content)
    if not result.ok:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "NEED_EDIT", "reason": result.reason, "suggestion": result.suggestion},
        )

    comment = Comment(
        post_id=post.id, user_id=me.id, content=body.content, is_ai=False,
        parent_id=root.id if root is not None else None,
    )
    db.add(comment)
    writer = db.get(User, post.user_id)
    if writer.deleted_at is None:
        create_notification(db, user_id=post.user_id, type="comment", post_id=post.id, actor_id=me.id)
    if root is not None and root.user_id is not None and root.user_id not in (me.id, post.user_id):
        create_notification(db, user_id=root.user_id, type="reply", post_id=post.id, actor_id=me.id)
    db.commit()
    db.refresh(comment)

    ai_reply = wants_ai_reply(db, post, root, me)
    if ai_reply:
        background.add_task(reply_in_thread, post.id, root.id, crisis=result.crisis)

    return CommentCreateOut(
        id=comment.id,
        content=comment.content,
        is_ai=False,
        parent_id=comment.parent_id,
        author=to_author(me, island),
        is_mine=True,
        created_at=comment.created_at,
        crisis_support=CRISIS_SUPPORT if result.crisis else None,
        ai_reply_pending=ai_reply,
    )


@router.delete("/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    post_id: int,
    comment_id: int,
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 댓글만 삭제. 행은 남기고 내용을 지워서 상세에 "삭제된 댓글입니다"로 보이게 한다."""
    comment = db.get(Comment, comment_id)
    if comment is None or comment.post_id != post_id or comment.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "댓글을 찾을 수 없습니다")
    if comment.user_id is None or comment.user_id != me.id:  # AI 댓글·남의 댓글은 삭제 불가
        raise HTTPException(status.HTTP_403_FORBIDDEN, "내 댓글만 삭제할 수 있습니다")
    comment.content = ""  # 원문은 남기지 않는다
    comment.deleted_at = datetime.now(timezone.utc)
    db.commit()


@router.post("/{post_id}/reactions", response_model=ReactionOut, dependencies=[limit_user("reaction", 60, 60)])
def toggle_reaction(post_id: int, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post, _ = get_visible_post(db, post_id, me)
    ensure_open_for_reaction(post)

    existing = db.scalar(select(Reaction).where(Reaction.post_id == post.id, Reaction.user_id == me.id))
    if existing is not None:
        db.delete(existing)
        reacted = False
    else:
        db.add(Reaction(post_id=post.id, user_id=me.id))
        writer = db.get(User, post.user_id)
        if writer.deleted_at is None:
            create_notification(db, user_id=post.user_id, type="reaction", post_id=post.id, actor_id=me.id)
        reacted = True

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        reacted = True

    return ReactionOut(reacted=reacted, reaction_count=reaction_count(db, post.id))

@router.post(
    "/{post_id}/comments/{comment_id}/thanks", response_model=ThanksOut,
    dependencies=[limit_user("thanks", 60, 600)],
)
def toggle_thanks(post_id: int, comment_id: int, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post, _ = get_visible_post(db, post_id, me)
    if post.user_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "글쓴이만 고마움을 전할 수 있습니다")
    comment = db.get(Comment, comment_id)
    unavailable = (
        comment is None
        or comment.post_id != post.id
        or comment.is_ai
        or comment.user_id is None
        or comment.user_id == me.id
        or comment.deleted_at is not None
        or comment.hidden_at is not None
        or comment.user_id in blocked_user_ids(db, me.id)
    )
    if unavailable:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "고마움을 전할 이웃 댓글을 찾을 수 없습니다")

    if comment.thanked_at is not None:
        comment.thanked_at = None
    else:
        comment.thanked_at = datetime.now(timezone.utc)
        neighbor = db.get(User, comment.user_id)
        if neighbor is not None and neighbor.deleted_at is None:
            create_notification(db, user_id=neighbor.id, type="thanks", post_id=post.id, actor_id=me.id)
    db.commit()
    return ThanksOut(thanked=comment.thanked_at is not None)


@router.get("/{post_id}/similar", response_model=list[SimilarPostOut], dependencies=[limit_user("similar", 30, 60)])
def similar_posts(post_id: int, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post, island = get_visible_post(db, post_id, me)
    excluded = blocked_user_ids(db, me.id) | {post.user_id}
    try:
        scored = search_similar_scored(db, post_text(post), island.id, exclude_user_ids=excluded, limit=20)
    except AIUnavailable:
        return []

    ids = [pid for pid, _ in scored if pid != post.id]
    answered = posts_with_neighbor_comment(db, ids)
    picked = [(pid, score) for pid, score in scored if pid in answered][:3]
    if not picked:
        return []

    posts = {p.id: p for p in db.scalars(select(Post).where(Post.id.in_([pid for pid, _ in picked])))}
    authors = {u.id: u for u in db.scalars(select(User).where(User.id.in_({p.user_id for p in posts.values()})))}
    counts = visible_comment_counts(db, list(posts))
    return [
        SimilarPostOut(
            id=p.id, title=p.title, preview=p.content[:80], topic=p.topic, comfort_type=p.comfort_type,
            created_at=p.created_at, comment_count=counts.get(p.id, 0),
            author=to_author(authors[p.user_id], island), similarity=round(score, 3),
        )
        for pid, score in picked
        if (p := posts.get(pid)) is not None
    ]
