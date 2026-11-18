from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user
from app.models import Island, Notification, Post, User
from app.queries import blocked_user_ids
from app.routers.islands import to_author
from app.schemas import NotificationListOut, NotificationOut, ReadRequest

router = APIRouter(prefix="/notifications", tags=["notifications"])

AI_NOTIFICATION_TYPES = ("comment", "reply")


@router.get("", response_model=NotificationListOut)
def list_notifications(
    limit: int = Query(20, ge=1, le=50),
    before_id: int | None = Query(None),
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hidden = blocked_user_ids(db, me.id)
    mine = [
        Notification.user_id == me.id,
        or_(Notification.actor_id.is_(None), Notification.actor_id.not_in(hidden)),
    ]
    readable = or_(
        Post.user_id == me.id,
        and_(Post.visibility == "public", Post.status == "published", Post.user_id.not_in(hidden)),
    )

    stmt = select(Notification, Post).join(Post, Post.id == Notification.post_id).where(*mine, readable)
    if before_id is not None:
        stmt = stmt.where(Notification.id < before_id)
    rows = db.execute(stmt.order_by(Notification.id.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    actor_ids = {n.actor_id for n, _ in rows if n.actor_id is not None}
    actors = {u.id: u for u in db.scalars(select(User).where(User.id.in_(actor_ids)))}
    islands = {i.id: i for i in db.scalars(select(Island).where(Island.id.in_({p.island_id for _, p in rows})))}
    unread_count = db.scalar(
        select(func.count()).select_from(Notification).join(Post, Post.id == Notification.post_id)
        .where(*mine, readable, Notification.is_read.is_(False))
    )

    return NotificationListOut(
        notifications=[
            NotificationOut(
                id=n.id,
                type=n.type,
                post_id=p.id,
                post_title=p.title,
                actor=None if n.actor_id is None else to_author(actors[n.actor_id], islands[p.island_id]),
                is_ai=n.actor_id is None and n.type in AI_NOTIFICATION_TYPES,
                is_read=n.is_read,
                created_at=n.created_at,
            )
            for n, p in rows
        ],
        unread_count=unread_count or 0,
        next_before_id=rows[-1][0].id if has_more else None,
    )


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(body: ReadRequest, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = update(Notification).where(Notification.user_id == me.id, Notification.is_read.is_(False))
    if body.post_id is not None:
        stmt = stmt.where(Notification.post_id == body.post_id)
    db.execute(stmt.values(is_read=True))
    db.commit()
