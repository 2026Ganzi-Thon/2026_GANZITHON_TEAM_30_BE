from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.ai.tasks import sync_post
from app.database import get_db
from app.deps import get_current_user
from app.moderation import is_protected, load_target, resolve_case, target_text
from app.models import ModerationCase, Post, Report, User

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(me: User = Depends(get_current_user)) -> User:
    if me.email.lower() not in config.ADMIN_EMAILS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "운영진만 사용할 수 있습니다")
    return me


class CaseOut(BaseModel):
    id: int
    target_type: str
    target_id: int
    state: str
    report_score: float
    ai_flagged: bool
    protected: bool
    appealed: bool
    appeal_reason: str | None
    preview: str
    reasons: list[str]
    updated_at: datetime


class ResolveIn(BaseModel):
    action: Literal["hide", "restore"]


@router.get("/moderation", response_model=list[CaseOut])
def list_cases(
    state: Literal["review", "hidden", "restored", "open"] = Query("open"),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(ModerationCase)
    if state == "open":
        stmt = stmt.where(ModerationCase.state.in_(("review", "hidden")))
    else:
        stmt = stmt.where(ModerationCase.state == state)
    cases = db.scalars(stmt.order_by(ModerationCase.appealed_at.is_(None), ModerationCase.updated_at.desc())).all()

    result = []
    for case in cases:
        target = load_target(db, case.target_type, case.target_id)
        reasons = db.scalars(
            select(Report.reason)
            .where(Report.target_type == case.target_type, Report.target_id == case.target_id)
            .order_by(Report.id.desc())
            .limit(5)
        ).all()
        result.append(CaseOut(
            id=case.id,
            target_type=case.target_type,
            target_id=case.target_id,
            state=case.state,
            report_score=case.report_score,
            ai_flagged=case.ai_flagged,
            protected=target is not None and is_protected(case, target),
            appealed=case.appealed_at is not None,
            appeal_reason=case.appeal_reason,
            preview=target_text(target)[:120] if target is not None else "",
            reasons=list(reasons),
            updated_at=case.updated_at,
        ))
    return result


@router.post("/moderation/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def resolve(
    case_id: int,
    body: ResolveIn,
    background: BackgroundTasks,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    case = db.get(ModerationCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "신고 건을 찾을 수 없습니다")
    target = resolve_case(db, case, body.action)
    if isinstance(target, Post):
        background.add_task(sync_post, target.id)
