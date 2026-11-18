import hashlib
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import config
from app.ai import check_text
from app.ai.tasks import sync_post
from app.database import SessionLocal
from app.models import Comment, ModerationCase, Notification, Post, Report, User


def now() -> datetime:
    return datetime.now(timezone.utc)


def reporter_weight(user: User, at: datetime) -> float:
    age_hours = (at - user.created_at).total_seconds() / 3600
    return 1.0 if age_hours >= config.REPORT_TRUSTED_ACCOUNT_HOURS else 0.5


def report_score(db: Session, target_type: str, target_id: int) -> float:
    reporters = db.scalars(
        select(User).join(Report, Report.reporter_id == User.id).where(
            Report.target_type == target_type,
            Report.target_id == target_id,
            Report.resolved_at.is_(None),
            User.deleted_at.is_(None),
        ).distinct()
    ).all()
    at = now()
    return sum(reporter_weight(u, at) for u in reporters)


def load_target(db: Session, target_type: str, target_id: int) -> Post | Comment | None:
    model = Post if target_type == "post" else Comment
    return db.get(model, target_id)


def target_text(target: Post | Comment) -> str:
    if isinstance(target, Post):
        return f"{target.title}\n{target.content}"
    return target.content


def content_hash(target: Post | Comment) -> str:
    return hashlib.sha256(target_text(target).encode("utf-8")).hexdigest()


def is_protected(case: ModerationCase, target: Post | Comment) -> bool:
    return case.restored_hash is not None and case.restored_hash == content_hash(target)


def target_post_id(target: Post | Comment) -> int:
    return target.id if isinstance(target, Post) else target.post_id


def is_hidden(target: Post | Comment) -> bool:
    if isinstance(target, Post):
        return target.status == "hidden"
    return target.hidden_at is not None


def set_hidden(target: Post | Comment, hidden: bool) -> None:
    if isinstance(target, Post):
        target.status = "hidden" if hidden else "published"
    else:
        target.hidden_at = now() if hidden else None


def notify_owner(db: Session, target: Post | Comment, kind: str) -> None:
    if target.user_id is None:
        return
    owner = db.get(User, target.user_id)
    if owner is None or owner.deleted_at is not None:
        return
    db.add(Notification(user_id=owner.id, type=kind, post_id=target_post_id(target), actor_id=None))


def get_or_create_case(db: Session, target_type: str, target: Post | Comment) -> ModerationCase:
    case = db.scalar(select(ModerationCase).where(
        ModerationCase.target_type == target_type, ModerationCase.target_id == target.id
    ))
    if case is None:
        case = ModerationCase(target_type=target_type, target_id=target.id, owner_id=target.user_id, state="review")
        db.add(case)
    return case


def unavailable(target: Post | Comment | None) -> bool:
    if target is None:
        return True
    if isinstance(target, Comment):
        return target.deleted_at is not None
    return False


def review_report(target_type: str, target_id: int) -> None:
    hidden_post_id = None
    with SessionLocal() as db:
        target = load_target(db, target_type, target_id)
        if unavailable(target):
            return
        score = report_score(db, target_type, target_id)
        if score < config.REPORT_HIDE_THRESHOLD:
            return

        case = get_or_create_case(db, target_type, target)
        case.report_score = score
        if is_hidden(target):
            db.commit()
            return

        if is_protected(case, target):
            case.state = "review"
            db.commit()
            return
        case.restored_hash = None

        result = check_text(target_text(target), kind="post" if target_type == "post" else "comment")
        case.ai_flagged = not result.ok
        if case.ai_flagged or score >= config.REPORT_FORCE_HIDE_THRESHOLD:
            set_hidden(target, True)
            case.state = "hidden"
            case.resolved_at = None
            notify_owner(db, target, "hidden")
            if isinstance(target, Post):
                hidden_post_id = target.id
        else:
            case.state = "review"
        db.commit()

    if hidden_post_id is not None:
        sync_post(hidden_post_id)


def resolve_case(db: Session, case: ModerationCase, action: str) -> Post | Comment | None:
    target = load_target(db, case.target_type, case.target_id)
    if target is None:
        return None
    if action == "hide":
        if not is_hidden(target):
            set_hidden(target, True)
            notify_owner(db, target, "hidden")
        case.state = "hidden"
        case.restored_hash = None
    else:
        was_hidden = is_hidden(target)
        set_hidden(target, False)
        db.execute(
            update(Report)
            .where(Report.target_type == case.target_type, Report.target_id == case.target_id, Report.resolved_at.is_(None))
            .values(resolved_at=now())
        )
        case.state = "restored"
        case.report_score = 0.0
        case.restored_hash = content_hash(target)
        if was_hidden:
            notify_owner(db, target, "restored")
    case.resolved_at = now()
    db.commit()
    return target
