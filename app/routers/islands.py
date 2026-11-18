from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.config import COMFORT_TYPES, LEFT_CHARACTER, LEFT_NICKNAME
from app.database import get_db
from app.deps import get_current_user
from app.models import Island, Post, User
from app.queries import (
    blocked_user_ids,
    get_accessible_island,
    has_unread_comment,
    island_post_count,
    keyword_filter,
    neighbor_comment_exists,
    posts_with_neighbor_comment,
    public_posts,
    visible_comment_counts,
)
from app.schemas import AuthorOut, IslandOut, LatestPostOut, NeighborOut, PostListOut, PostSummary

router = APIRouter(prefix="/islands", tags=["islands"])


def to_author(user: User, island: Island) -> AuthorOut:
    if user.deleted_at is not None:
        return AuthorOut(user_id = user.id, nickname=LEFT_NICKNAME, character=LEFT_CHARACTER, job=None)
    return AuthorOut(
        user_id=user.id,
        nickname=user.nickname,
        character=user.character,
        job=user.job if island.type == "common" else None,
    )


@router.get("", response_model=list[IslandOut])
def list_islands(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """섬 선택 화면: 내 직무섬을 먼저, 그다음 통합섬."""
    my_island = db.scalar(select(Island).where(Island.type == "job", Island.job == user.job))
    common = db.scalar(select(Island).where(Island.type == "common"))
    hidden = blocked_user_ids(db, user.id)
    result = []
    for island in [my_island, common]:
        if island is None:
            continue
        result.append(IslandOut(
            id=island.id,
            type=island.type,
            name=island.name,
            is_mine=island.type == "job",
            post_count=island_post_count(db, island.id, hidden),
            has_new_comment=has_unread_comment(db, user.id, island.id),
        ))
    return result


@router.get("/{island_id}/neighbors", response_model=list[NeighborOut])
def list_neighbors(island_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    island = get_accessible_island(db, island_id, user)
    hidden = blocked_user_ids(db, user.id)

    stats = (
        select(Post.user_id, func.count(Post.id).label("cnt"), func.max(Post.created_at).label("latest"))
        .where(Post.island_id == island.id, Post.visibility == "public", Post.status == "published")
        .group_by(Post.user_id)
        .subquery()
    )
    rows = db.execute(
        select(User, Post, stats.c.cnt)
        .join(stats, stats.c.user_id == User.id)
        .join(Post, (Post.user_id == User.id) & (Post.created_at == stats.c.latest) & (Post.island_id == island.id))
        .where(User.id.not_in(hidden), User.deleted_at.is_(None))
        .order_by(stats.c.latest.desc())
    ).all()

    neighbors: dict[int, NeighborOut] = {}
    for u, post, cnt in rows:
        if u.id in neighbors:  
            continue
        neighbors[u.id] = NeighborOut(
            author=to_author(u, island),
            latest_post=LatestPostOut(id=post.id, title=post.title, created_at=post.created_at),
            post_count=cnt,
            is_me=u.id == user.id,
        )

    # 내 캐릭터는 글이 없어도 지도에 나와야 한다
    if user.id not in neighbors:
        neighbors[user.id] = NeighborOut(author=to_author(user, island), latest_post=None, post_count=0, is_me=True)
    return list(neighbors.values())


@router.get("/{island_id}/posts", response_model=PostListOut)
def list_island_posts(
    island_id: int,
    comfort_type: list[str] | None = Query(None, description=f"위로 방식 필터: {list(COMFORT_TYPES)}"),
    q: str | None = Query(None, min_length=1, max_length=50, description="제목·본문 검색어"),
    limit: int = Query(20, ge=1, le=50),
    before_id: int | None = Query(None, description="더 보기: 이전 응답의 next_before_id"),
    waiting: bool = Query(False, description="true면 아직 이웃 댓글이 없는 고민만"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """최근 고민 목록(업로드순). 위로 방식 필터와 검색어를 함께 적용할 수 있다."""
    island = get_accessible_island(db, island_id, user)
    hidden = blocked_user_ids(db, user.id)

    conditions = [Post.island_id == island.id, Post.user_id.not_in(hidden)]
    if comfort_type:
        if any(c not in COMFORT_TYPES for c in comfort_type):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"위로 방식은 {list(COMFORT_TYPES)} 중 하나여야 합니다")
        conditions.append(Post.comfort_type.in_(comfort_type))
    if q:
        conditions.append(keyword_filter(q))
    if waiting:
        conditions.append(~neighbor_comment_exists())

    stmt = public_posts().where(*conditions)
    if before_id is not None:
        stmt = stmt.where(Post.id < before_id)
    # limit+1개를 가져와서 하나 더 있으면 '다음 페이지 있음'으로 판단
    posts = db.scalars(stmt.order_by(Post.id.desc()).limit(limit + 1)).all()
    has_more = len(posts) > limit
    posts = posts[:limit]

    post_ids = [p.id for p in posts]
    counts = visible_comment_counts(db, post_ids)
    answered = posts_with_neighbor_comment(db, post_ids)
    authors = {u.id: u for u in db.scalars(select(User).where(User.id.in_({p.user_id for p in posts})))}

    user_ids = db.scalars(public_posts().with_only_columns(Post.user_id).where(*conditions).distinct()).all()

    return PostListOut(
        posts=[
            PostSummary(
                id=p.id,
                title=p.title,
                preview=p.content[:80],
                topic=p.topic,
                comfort_type=p.comfort_type,
                created_at=p.created_at,
                comment_count=counts.get(p.id, 0),
                author=to_author(authors[p.user_id], island),
                waiting=p.id not in answered,
            )
            for p in posts
        ],
        user_ids=list(user_ids),
        next_before_id=posts[-1].id if has_more else None,
    )
