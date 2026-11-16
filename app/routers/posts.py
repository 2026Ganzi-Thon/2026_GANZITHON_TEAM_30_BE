from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.ai import check_text
from app.database import get_db
from app.deps import get_current_user
from app.models import Comment, Island, Notification, Post, Reaction, User
from app.queries import blocked_user_ids, create_notification, get_accessible_island
from app.routers.islands import to_author
from app.schemas import CommentCreate, CommentOut, PostDetailOut, ReactionOut

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

    if is_mine:
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
        comments=[
            CommentOut(
                id=c.id,
                content=c.content,
                is_ai=c.is_ai,
                author=None if c.user_id is None else to_author(users[c.user_id], island),
                is_mine=c.user_id == me.id,
                created_at=c.created_at,
            )
            for c in comments
        ],
    )


@router.post("/{post_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def create_comment(
    post_id: int,
    body: CommentCreate,
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post, island = get_visible_post(db, post_id, me)
    ensure_open_for_reaction(post)

    result = check_text(body.content)
    if not result.ok:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"reason": result.reason, "suggestion": result.suggestion},
        )

    comment = Comment(post_id=post.id, user_id=me.id, content=body.content, is_ai=False)
    db.add(comment)
    writer = db.get(User, post.user_id)
    if writer.deleted_at is None:
        create_notification(db, user_id=post.user_id, type="comment", post_id=post.id, actor_id=me.id)
    db.commit()
    db.refresh(comment)
    return CommentOut(
        id=comment.id,
        content=comment.content,
        is_ai=False,
        author=to_author(me, island),
        is_mine=True,
        created_at=comment.created_at,
    )


@router.delete("/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    post_id: int,
    comment_id: int,
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comment = db.get(Comment, comment_id)
    if comment is None or comment.post_id != post_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "댓글을 찾을 수 없습니다")
    if comment.user_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "내 댓글만 삭제할 수 있습니다")
    db.delete(comment)
    db.commit()


@router.post("/{post_id}/reactions", response_model=ReactionOut)
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