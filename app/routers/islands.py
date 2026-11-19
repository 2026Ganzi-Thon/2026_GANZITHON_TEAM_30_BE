import math
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app import presence
from app.config import COMFORT_TYPES, FOOTPRINT_HOURS, ISLAND_COUNT_DAYS, LEFT_CHARACTER, LEFT_NICKNAME
from app.database import get_db
from app.deps import get_current_user
from app.models import Comment, Island, IslandVisit, Post, User
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
from app.ratelimit import limit_user
from app.ai import CRISIS_SUPPORT
from app.keeper import keeper_info
from app.titles import attach_titles
from app.schemas import (
    AuthorOut, BottleOut, FootprintOut, FootprintsOut, IslandOut, KeeperOut, LatestPostOut, NeighborOut, PostListOut,
    PostSummary, PresenceIn, PresenceOut, TemperatureOut,
)

router = APIRouter(prefix="/islands", tags=["islands"])


def to_author(user: User, island: Island) -> AuthorOut:
    if user.deleted_at is not None:
        return AuthorOut(user_id = user.id, nickname=LEFT_NICKNAME, character=LEFT_CHARACTER, job=None)
    return AuthorOut(
        user_id=user.id,
        nickname=user.nickname,
        character=user.character,
        color=user.color or "original",
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
            latest_post=LatestPostOut(
                id=post.id, title=post.title, created_at=post.created_at, map_x=post.map_x, map_y=post.map_y
            ),
            post_count=cnt,
            is_me=u.id == user.id,
        )

    # 내 캐릭터는 글이 없어도 지도에 나와야 한다
    if user.id not in neighbors:
        neighbors[user.id] = NeighborOut(author=to_author(user, island), latest_post=None, post_count=0, is_me=True)
    attach_titles(db, [n.author for n in neighbors.values()])
    return list(neighbors.values())


@router.post(
    "/{island_id}/presence", response_model=list[PresenceOut], dependencies=[limit_user("presence", 60, 60)]
)
def update_presence(
    island_id: int, body: PresenceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """내 위치를 알리고, 지금 같은 섬을 돌아다니는 이웃들의 위치를 받는다. FE는 몇 초마다 부른다."""
    island = get_accessible_island(db, island_id, user)
    presence.update(island.id, user.id, body.x, body.y)
    if presence.should_record(island.id, user.id):
        record_visit(db, island.id, user.id, body.x, body.y)

    hidden = blocked_user_ids(db, user.id) | {user.id}  # 3초마다 불리므로 차단 목록은 한 번만 조회
    others = {u: pos for u, pos in presence.online(island.id).items() if u not in hidden}
    if not others:
        return []
    users = db.scalars(select(User).where(User.id.in_(others), User.deleted_at.is_(None))).all()
    return [PresenceOut(author=to_author(u, island), x=others[u.id][0], y=others[u.id][1]) for u in users]


def record_visit(db: Session, island_id: int, user_id: int, x: float, y: float) -> None:
    """발자국: 이 섬에서 마지막으로 머문 자리와 시각을 남긴다 (한 사람·한 섬당 한 줄)."""
    visit = db.scalar(select(IslandVisit).where(IslandVisit.island_id == island_id, IslandVisit.user_id == user_id))
    now = datetime.now(timezone.utc)
    if visit is None:
        db.add(IslandVisit(island_id=island_id, user_id=user_id, x=x, y=y, visited_at=now))
    else:
        visit.x, visit.y, visit.visited_at = x, y, now
    try:
        db.commit()
    except IntegrityError:  # 같은 사람이 거의 동시에 두 번 보낸 경우
        db.rollback()


@router.get("/{island_id}/footprints", response_model=FootprintsOut)
def get_footprints(island_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """최근 하루 동안 이 섬을 다녀간 이웃들. 지금 접속한 사람이 없어도 섬이 비어 보이지 않게 한다.
    지도를 돌아다닌 기록과 함께, 이 섬에 고민이나 위로를 남긴 이웃도 다녀간 것으로 본다."""
    island = get_accessible_island(db, island_id, user)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=FOOTPRINT_HOURS)

    seen: dict[int, tuple[float | None, float | None, datetime]] = {}

    def mark(user_id: int | None, when: datetime, x: float | None = None, y: float | None = None) -> None:
        if user_id is None:
            return
        old = seen.get(user_id)
        if old is None:
            seen[user_id] = (x, y, when)
        else:
            seen[user_id] = (old[0] if x is None else x, old[1] if y is None else y, max(old[2], when))

    for visit in db.scalars(
        select(IslandVisit).where(IslandVisit.island_id == island.id, IslandVisit.visited_at >= since)
    ):
        mark(visit.user_id, visit.visited_at, visit.x, visit.y)
    for post in db.scalars(public_posts().where(Post.island_id == island.id, Post.created_at >= since)):
        mark(post.user_id, post.created_at)
    for comment in db.scalars(
        select(Comment).join(Post, Post.id == Comment.post_id)
        .where(Post.island_id == island.id, Comment.created_at >= since,
               Comment.deleted_at.is_(None), Comment.hidden_at.is_(None))
    ):
        mark(comment.user_id, comment.created_at)

    hidden = blocked_user_ids(db, user.id) | {user.id}
    ids = [u for u in seen if u not in hidden]
    users = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_(ids), User.deleted_at.is_(None)))
    } if ids else {}
    recent = sorted(users, key=lambda u: seen[u][2], reverse=True)
    return FootprintsOut(
        visitors=len(users),
        hours=FOOTPRINT_HOURS,
        footprints=[
            FootprintOut(
                user_id=u, character=users[u].character, x=seen[u][0], y=seen[u][1],
                hours_ago=round((now - seen[u][2]).total_seconds() / 3600, 1),
            )
            for u in recent[:30]
        ],
    )


@router.get("/{island_id}/bottle", response_model=BottleOut)
def get_bottle(
    island_id: int,
    skip: list[int] = Query([], description="이미 열어 본 유리병 글 id (다시 안 나오게)"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """유리병 편지: 다른 섬에서 떠내려온 고민 하나. 직무섬에선 통합섬 고민이, 통합섬에선 내 직무섬 고민이 온다.
    그쪽에 없으면 이 섬의 예전 고민을 건진다. 글쓴이가 뒤에 덧붙인 이야기가 있는 글을 더 자주 고른다."""
    island = get_accessible_island(db, island_id, user)
    if island.type == "common":
        other = db.scalar(select(Island).where(Island.type == "job", Island.job == user.job))
    else:
        other = db.scalar(select(Island).where(Island.type == "common"))

    hidden = blocked_user_ids(db, user.id) | {user.id}
    base = (
        public_posts().join(User, User.id == Post.user_id)
        .where(User.deleted_at.is_(None), Post.user_id.not_in(hidden), Post.id.not_in(skip[:100]))
    )
    has_story = (
        select(Comment.id)
        .where(Comment.post_id == Post.id, Comment.user_id == Post.user_id,
               Comment.deleted_at.is_(None), Comment.hidden_at.is_(None))
        .exists()
    )
    post = None
    for target in [i for i in (other, island) if i is not None]:
        candidates = base.where(Post.island_id == target.id)
        if random.random() < 0.6:
            post = db.scalar(candidates.where(has_story).order_by(func.random()).limit(1))
        post = post or db.scalar(candidates.order_by(func.random()).limit(1))
        if post:
            break
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "아직 떠내려온 유리병이 없어요")

    from_island = db.get(Island, post.island_id)
    writer = db.get(User, post.user_id)
    follow_up = db.scalar(
        select(Comment.content)
        .where(Comment.post_id == post.id, Comment.user_id == post.user_id,
               Comment.deleted_at.is_(None), Comment.hidden_at.is_(None))
        .order_by(Comment.id.desc())
        .limit(1)
    )
    comment_count = db.scalar(
        select(func.count(Comment.id))
        .where(Comment.post_id == post.id, Comment.deleted_at.is_(None), Comment.hidden_at.is_(None))
    ) or 0
    return BottleOut(
        post_id=post.id, island_id=from_island.id, island_name=from_island.name, topic=post.topic,
        title=post.title, content=post.content, comfort_type=post.comfort_type, created_at=post.created_at,
        author=to_author(writer, from_island), follow_up=follow_up, comment_count=comment_count,
    )


def island_temperature(posts: int, comments: int) -> float:
    """글·댓글이 쌓일수록 오르되 끝없이 오르지 않게: 12°에서 시작해 40°에 가까워진다."""
    warmth = posts + comments * 0.5
    return round(12 + 28 * (1 - math.exp(-warmth / 30)), 1)


@router.get("/{island_id}/temperature", response_model=TemperatureOut)
def get_temperature(island_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """섬 중앙 모닥불 온도. 최근 공개 고민과 위로 댓글 수로 정한다."""
    island = get_accessible_island(db, island_id, user)
    since = datetime.now(timezone.utc) - timedelta(days=ISLAND_COUNT_DAYS)
    visible = public_posts().where(Post.island_id == island.id).subquery()
    posts = db.scalar(select(func.count()).select_from(visible).where(visible.c.created_at >= since)) or 0
    comments = db.scalar(
        select(func.count(Comment.id))
        .join(visible, visible.c.id == Comment.post_id)
        .where(Comment.created_at >= since, Comment.deleted_at.is_(None), Comment.hidden_at.is_(None))
    ) or 0
    temperature = island_temperature(posts, comments)
    level = "hot" if temperature >= 36.5 else "warm" if temperature >= 30 else "mild" if temperature >= 20 else "cold"
    return TemperatureOut(
        temperature=temperature, level=level, posts=posts, comments=comments, days=ISLAND_COUNT_DAYS,
        online=len(presence.online(island.id)),
    )


@router.get("/{island_id}/keeper", response_model=KeeperOut)
def get_keeper(island_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """섬지기(운영자 캐릭터): 인사, 이번 주의 질문, 최근 7일 섬 소식, 이용 원칙, 위기 상담 안내."""
    island = get_accessible_island(db, island_id, user)
    return keeper_info(db, island, CRISIS_SUPPORT)


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

    result = PostListOut(
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
    attach_titles(db, [p.author for p in result.posts])
    return result
