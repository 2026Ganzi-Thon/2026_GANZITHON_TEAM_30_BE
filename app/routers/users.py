from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user
from app.models import Comment, Island, Notification, Post, User
from app.queries import blocked_user_ids, get_accessible_island, public_posts
from app.routers.islands import to_author
from app.schemas import AuthorOut, MyCommentOut, MyPostOut, PostSummary

router = APIRouter(prefix="/users", tags=["users"])


def get_visible_user(db: Session, user_id: int, me: User) -> User:
    target = db.get(User, user_id)
    if target is None or target.deleted_at is not None or target.id in blocked_user_ids(db, me.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다")
    return target


@router.get("/me/posts", response_model=list[MyPostOut])
def get_my_posts(
    visibility: str | None = Query(None, pattern="^(public|private)$", description="비우면 전체"),
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Post).where(Post.user_id == me.id)
    if visibility is not None:
        stmt = stmt.where(Post.visibility == visibility)
    posts = db.scalars(stmt.order_by(Post.id.desc())).all()

    post_ids = [p.id for p in posts]
    counts = dict(db.execute(
        select(Comment.post_id, func.count()).where(Comment.post_id.in_(post_ids)).group_by(Comment.post_id)
    ).all()) if post_ids else {}
    islands = {i.id: i for i in db.scalars(select(Island).where(Island.id.in_({p.island_id for p in posts})))}
    unread = set(db.scalars(
        select(Notification.post_id).where(
            Notification.user_id == me.id, Notification.is_read.is_(False), Notification.post_id.in_(post_ids)
        )
    ))

    return [
        MyPostOut(
            id=p.id, title=p.title, preview=p.content[:80], topic=p.topic, comfort_type=p.comfort_type,
            created_at=p.created_at, comment_count=counts.get(p.id, 0), author=to_author(me, islands[p.island_id]),
            visibility=p.visibility, status=p.status, has_unread=p.id in unread,
        )
        for p in posts
    ]


@router.get("/me/comments", response_model=list[MyCommentOut])
def get_my_comments(me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Comment, Post).join(Post, Post.id == Comment.post_id)
        .where(Comment.user_id == me.id)
        .order_by(Comment.id.desc())
    ).all()
    hidden = blocked_user_ids(db, me.id)

    def can_see(p: Post) -> bool:
        if p.user_id == me.id:
            return True
        return p.visibility == "public" and p.status == "published" and p.user_id not in hidden

    return [
        MyCommentOut(
            id=c.id,
            content=c.content,
            created_at=c.created_at,
            post_id=p.id if can_see(p) else None,
            post_title=p.title if can_see(p) else "삭제된 글",
        )
        for c, p in rows
    ]


@router.get("/{user_id}/profile", response_model=AuthorOut)
def get_profile(
    user_id: int,
    island_id: int = Query(..., description="지금 보고 있는 섬 (통합섬이면 직무 표시)"),
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """간단 프로필: 닉네임·캐릭터 (+통합섬이면 직무). 연차는 절대 포함하지 않는다."""
    island = get_accessible_island(db, island_id, me)
    return to_author(get_visible_user(db, user_id, me), island)


@router.get("/{user_id}/posts", response_model=list[PostSummary])
def get_user_posts(
    user_id: int,
    island_id: int = Query(...),
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    island = get_accessible_island(db, island_id, me)
    target = get_visible_user(db, user_id, me)
    posts = db.scalars(
        public_posts().where(Post.user_id == target.id, Post.island_id == island.id).order_by(Post.id.desc())
    ).all()
    counts = dict(db.execute(
        select(Comment.post_id, func.count()).where(Comment.post_id.in_([p.id for p in posts])).group_by(Comment.post_id)
    ).all()) if posts else {}
    author = to_author(target, island)
    return [
        PostSummary(
            id=p.id, title=p.title, preview=p.content[:80], topic=p.topic, comfort_type=p.comfort_type,
            created_at=p.created_at, comment_count=counts.get(p.id, 0), author=author,
        )
        for p in posts
    ]
