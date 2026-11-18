from datetime import datetime
from statistics import median

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Comment, ModerationCase, Notification
from app.queries import public_posts
from app.ratelimit import limit_ip

router = APIRouter(prefix="/stats", tags=["stats"])


class ImpactOut(BaseModel):
    public_posts: int
    posts_with_first_response: int
    median_minutes_to_first_response: float | None
    posts_with_neighbor_response: int
    median_minutes_to_neighbor_response: float | None
    ai_conversations: int
    ai_follow_up_replies: int
    neighbor_comments: int
    thanked_comments: int
    invites_sent: int
    invited_posts_answered: int
    reports_reviewed: int
    reports_restored: int


def minutes_between(start: datetime, end: datetime) -> float:
    return max((end - start).total_seconds() / 60, 0.0)


def rounded_median(values: list[float]) -> float | None:
    return round(median(values), 1) if values else None


@router.get("/impact", response_model=ImpactOut, dependencies=[limit_ip("stats", 30, 60)])
def impact(db: Session = Depends(get_db)):
    posts = db.scalars(public_posts()).all()
    post_by_id = {p.id: p for p in posts}
    comments = db.scalars(
        select(Comment)
        .where(Comment.post_id.in_(post_by_id), Comment.deleted_at.is_(None), Comment.hidden_at.is_(None))
        .order_by(Comment.id)
    ).all() if post_by_id else []

    invited = set(db.scalars(
        select(Notification.post_id).where(Notification.type == "invite", Notification.post_id.in_(post_by_id)).distinct()
    )) if post_by_id else set()

    first_any: dict[int, datetime] = {}
    first_neighbor: dict[int, datetime] = {}
    ai_threads: set[int] = set()
    ai_follow_ups = 0
    neighbor_comments = 0
    for c in comments:
        post = post_by_id[c.post_id]
        first_any.setdefault(post.id, c.created_at)
        if c.is_ai and c.parent_id is not None:
            ai_follow_ups += 1
            ai_threads.add(c.parent_id)
        if not c.is_ai and c.user_id != post.user_id:
            neighbor_comments += 1
            first_neighbor.setdefault(post.id, c.created_at)

    return ImpactOut(
        public_posts=len(posts),
        posts_with_first_response=len(first_any),
        median_minutes_to_first_response=rounded_median(
            [minutes_between(post_by_id[pid].created_at, t) for pid, t in first_any.items()]
        ),
        posts_with_neighbor_response=len(first_neighbor),
        median_minutes_to_neighbor_response=rounded_median(
            [minutes_between(post_by_id[pid].created_at, t) for pid, t in first_neighbor.items()]
        ),
        ai_conversations=len(ai_threads),
        ai_follow_up_replies=ai_follow_ups,
        neighbor_comments=neighbor_comments,
        thanked_comments=sum(1 for c in comments if c.thanked_at is not None),
        invites_sent=len(invited),
        invited_posts_answered=len(invited & set(first_neighbor)),
        reports_reviewed=count_cases(db, None),
        reports_restored=count_cases(db, "restored"),
    )


def count_cases(db: Session, state: str | None) -> int:
    stmt = select(func.count()).select_from(ModerationCase)
    if state is not None:
        stmt = stmt.where(ModerationCase.state == state)
    return db.scalar(stmt) or 0
