from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.config import LEFT_CHARACTER, LEFT_NICKNAME
from app.database import get_db
from app.deps import get_current_user
from app.models import Block, Comment, Report, User
from app.queries import blocked_user_ids
from app.routers.posts import get_visible_post
from app.schemas import BlockCreate, BlockedUserOut, ReportCreate

router = APIRouter(tags=["safety"])


@router.post("/reports", status_code=status.HTTP_204_NO_CONTENT)
def create_report(body: ReportCreate, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.target_type == "post":
        post, _ = get_visible_post(db, body.target_id, me)
        owner_id = post.user_id
    else:
        comment = db.get(Comment, body.target_id)
        if comment is None or (comment.user_id is not None and comment.user_id in blocked_user_ids(db, me.id)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "댓글을 찾을 수 없습니다")
        get_visible_post(db, comment.post_id, me)
        owner_id = comment.user_id

    if owner_id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "내가 쓴 글·댓글은 신고할 수 없습니다")

    db.add(Report(reporter_id=me.id, target_type=body.target_type, target_id=body.target_id, reason=body.reason))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 신고한 대상입니다")


@router.get("/blocks", response_model=list[BlockedUserOut])
def list_blocks(me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Block, User).join(User, User.id == Block.blocked_id)
        .where(Block.blocker_id == me.id)
        .order_by(Block.id.desc())
    ).all()
    return [
        BlockedUserOut(
            user_id=u.id,
            nickname=LEFT_NICKNAME if u.deleted_at else u.nickname,
            character=LEFT_CHARACTER if u.deleted_at else u.character,
            blocked_at=b.created_at,
        )
        for b, u in rows
    ]


@router.post("/blocks", status_code=status.HTTP_204_NO_CONTENT)
def create_block(body: BlockCreate, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.user_id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "자기 자신은 차단할 수 없습니다")
    target = db.get(User, body.user_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다")

    db.add(Block(blocker_id=me.id, blocked_id=target.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  


@router.delete("/blocks/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(user_id: int, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = db.execute(delete(Block).where(Block.blocker_id == me.id, Block.blocked_id == user_id))
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "차단한 사용자가 아닙니다")
    db.commit()
