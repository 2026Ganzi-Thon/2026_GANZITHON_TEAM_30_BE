"""섬 고민 리포트: 섬에 쌓인 공개 고민을 모아 "이 섬엔 어떤 고민이 많은지"를 숫자로 보여 준다.

무엇을 세나 (모두 공개·게시된 글만, 나와 차단 관계인 사람의 글은 뺀다)
  1. 주제 순위   글마다 고른 주제(topic)를 세어 상위 5개 + 비율, 큰 분류(업무·진로·감정·관계)별 비율
  2. 주제 추이   최근 7일과 그 전 7일을 비교해 가장 많이 늘어난 주제
  3. 언제 올라오나  한국 시간 기준 요일 × 시간대(아침·낮·저녁·밤) 중 가장 많은 칸 (섬지기 한마디와 같은 칸 나누기)
  4. 바라는 위로  들어주세요 / 경험을 나눠주세요 / 함께 생각해주세요 비율
  5. 비슷한 고민 묶음  저장해 둔 고민 벡터끼리 유사도를 재서, 서로 닮은 글이 3개 이상 모인 묶음 (주제 선택과 상관없이 "내용"으로 묶음)
  6. 내 공명     내 최근 고민과 닮은 고민을 쓴 이웃 수, 가장 닮은 정도, 내 주제가 이 섬에서 몇 번째로 많은지
  7. 직무별 비교  직무섬마다 가장 많은 주제 (글이 5개 이상인 섬만)
  8. 오늘의 두 고민  최근 24시간 공감이 가장 많이 모인 고민 1개 + 아직 이웃 답을 기다리는 고민 1개를 나란히.
     인기 순위표로 만들면 이미 관심 받은 글에만 시선이 몰리므로, 일부러 1개씩만 짝지어 보여 준다.

갱신: 매일 한국 시간 아침 8시. 그 시각까지 쌓인 글만 센다 → 하루 동안은 같은 리포트를 본다
(유리병 편지와 같은 리듬). 같은 사람·같은 날 결과는 메모리에 두어 다시 계산하지 않는다.

개인 글 내용은 내보내지 않는다. 묶음의 대표 제목만 보여 주는데, 이건 원래 피드에서 누구나 보는 공개 글 제목이다.
"""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import client, settings
from app.ai.models import PostEmbedding
from app.config import COMFORT_TYPES, TOPIC_CATEGORIES
from app.keeper_lines import SLOT_NAMES, moment_name, moment_of
from app.models import Island, Post, Reaction, User
from app.queries import neighbor_comment_exists, public_posts

KST = timezone(timedelta(hours=9))
DAILY_HOUR = 8  # 리포트·유리병 편지가 새로 바뀌는 시각 (한국 시간)
MIN_POSTS = 5  # 글이 이보다 적으면 리포트 대신 "조금 더 쌓이면 보여 줄게요"
MIN_WARM = 2  # 오늘 공감이 2개 이상 모인 글만 "공감이 모인 고민"으로
MIN_GROUP = 3  # 비슷한 고민 묶음은 3개 이상 모였을 때만
TOP_TOPICS = 5
TOP_GROUPS = 3
MAX_POSTS = 500  # 유사도는 글 수의 제곱만큼 계산하므로 최근 500개까지만
WEEK = timedelta(days=7)
SLOTS = list(SLOT_NAMES)  # morning, day, evening, night

# 저장된 고민(passage)끼리의 유사도 기준. 검색어↔고민(0.26)보다 훨씬 높게 나와서 따로 둔다.
# upstage: 실제 고민 85개로 재 보니 0.55면 "야근·퇴근 후 업무 생각"처럼 결이 다른 글까지 한 묶음,
# 0.58이면 "팀장과 갈등 · 회의 때 의견 · 날카로운 피드백"처럼 한 가지 결로 모였다.
PAIR_SIMILARITY = {"upstage": 0.58, "gemini": 0.75, "local": 0.25}

CATEGORY_OF = {topic: category for category, topics in TOPIC_CATEGORIES.items() for topic in topics}


class Share(BaseModel):
    key: str  # 주제·분류·위로 방식 이름 (위로 방식은 empathy 같은 코드)
    label: str  # 화면에 보일 글자
    count: int
    ratio: float  # 0~1


class TopicTrend(BaseModel):
    topic: str
    this_week: int
    last_week: int


class TimeShare(BaseModel):
    busiest: str | None  # "월요일 밤"
    busiest_count: int = 0
    days: list[int]  # 월~일 글 수
    slots: list[Share]  # 아침·낮·저녁·밤


class SimilarGroup(BaseModel):
    post_id: int  # 묶음의 대표 글 (묶음 안에서 닮은 글이 가장 많은 글)
    title: str
    topic: str
    size: int
    similarity: float  # 대표 글과 나머지 글의 평균 유사도


class MyResonance(BaseModel):
    post_id: int
    title: str
    topic: str
    similar_posts: int  # 이 섬에서 내 고민과 닮은 다른 사람의 고민 수
    neighbors: int  # 그 고민을 쓴 이웃 수 (한 사람이 여러 개 써도 1명)
    share: float  # 다른 사람 고민 중 닮은 고민의 비율
    top_similarity: float | None
    topic_rank: int | None  # 내 주제가 이 섬에서 몇 번째로 많은지


class PostPick(BaseModel):
    post_id: int
    title: str
    topic: str
    count: int  # warmest: 최근 24시간 공감 수 / waiting: 0


class JobTop(BaseModel):
    job: str
    island_id: int
    island_name: str
    topic: str
    ratio: float
    posts: int


class InsightsOut(BaseModel):
    island_id: int
    island_name: str
    enough: bool  # False면 글이 적어 리포트를 보여 주지 않는다
    min_posts: int = MIN_POSTS
    total_posts: int
    week_posts: int
    headlines: list[str]  # 한 줄 요약 (서버에서 문장으로 만들어 FE는 그대로 보여 줌)
    topics: list[Share]
    topic_kinds: int  # 이 섬에 나온 주제 가짓수
    categories: list[Share]
    rising: TopicTrend | None
    time: TimeShare
    comfort: list[Share]
    groups: list[SimilarGroup]
    me: MyResonance | None
    jobs: list[JobTop]
    warmest: PostPick | None
    waiting: PostPick | None
    as_of: datetime  # 이 리포트의 기준 시각 (오늘 아침 8시)
    next_at: datetime  # 다음 갱신 시각 (내일 아침 8시)


# ---------- 문장 만들기 ----------

def _has_final(word: str) -> bool:
    """마지막 글자에 받침이 있나 (한글이 아니면 받침 없음으로 본다)."""
    code = ord(word[-1]) - 0xAC00 if word else -1
    return 0 <= code < 11172 and code % 28 != 0


def copula(word: str) -> str:
    return "이에요" if _has_final(word) else "예요"


def with_and(word: str) -> str:
    return "과" if _has_final(word) else "와"


def topic_mark(word: str) -> str:
    return "은" if _has_final(word) else "는"


def pct(ratio: float) -> int:
    return round(ratio * 100)


# ---------- 계산 ----------

def daily_window(now: datetime) -> tuple[datetime, datetime]:
    """(오늘 기준 시각, 다음 기준 시각). 아침 8시 전이면 아직 어제 8시가 기준."""
    kst = now.astimezone(KST)
    start = kst.replace(hour=DAILY_HOUR, minute=0, second=0, microsecond=0)
    if kst < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


def _kst(dt: datetime) -> datetime:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(KST)


def _shares(counter: Counter, total: int, labels: dict[str, str] | None = None, top: int | None = None) -> list[Share]:
    return [
        Share(key=key, label=(labels or {}).get(key, key), count=count, ratio=round(count / total, 3))
        for key, count in counter.most_common(top)
    ] if total else []


def topic_trend(posts: list[Post], now: datetime) -> TopicTrend | None:
    """최근 7일 vs 그 전 7일. 이번 주 2개 이상이면서 가장 많이 늘어난 주제."""
    this_week = Counter(p.topic for p in posts if p.created_at >= now - WEEK)
    last_week = Counter(p.topic for p in posts if now - 2 * WEEK <= p.created_at < now - WEEK)
    best = None
    for topic, count in this_week.items():
        grew = count - last_week.get(topic, 0)
        if count >= 2 and grew > 0 and (best is None or grew > best[0]):
            best = (grew, TopicTrend(topic=topic, this_week=count, last_week=last_week.get(topic, 0)))
    return best[1] if best else None


def time_share(posts: list[Post]) -> TimeShare:
    cells = Counter(moment_of(_kst(p.created_at)) for p in posts)
    days = [sum(c for (d, _), c in cells.items() if d == day) for day in range(7)]
    slots = Counter({slot: sum(c for (_, s), c in cells.items() if s == slot) for slot in SLOTS})
    top = cells.most_common(1)
    return TimeShare(
        busiest=moment_name(*top[0][0]) if top else None, busiest_count=top[0][1] if top else 0, days=days,
        slots=[Share(key=s, label=SLOT_NAMES[s], count=slots[s], ratio=round(slots[s] / len(posts), 3) if posts else 0)
               for s in SLOTS],
    )


_vector_cache: dict[int, tuple[tuple, list[int], np.ndarray]] = {}


def island_vectors(db: Session, island_id: int) -> tuple[list[int], np.ndarray]:
    """섬의 공개 고민 벡터 (길이 1로 맞춘 행렬). 벡터가 바뀌지 않았으면 메모리에 둔 것을 다시 쓴다
    (upstage 벡터는 4096칸이라 매번 JSON을 푸는 게 가장 느림)."""
    base = (
        select(PostEmbedding.post_id, PostEmbedding.vector_json)
        .join(Post, Post.id == PostEmbedding.post_id)
        .where(Post.island_id == island_id, Post.visibility == "public", Post.status == "published",
               PostEmbedding.model == client.embedding_model())
    )
    # 개수·가장 큰 글 번호·마지막 수정 시각이 같으면 벡터도 같다 (가벼운 질의 한 번)
    key = tuple(db.execute(
        select(func.count(PostEmbedding.post_id), func.max(PostEmbedding.post_id), func.max(PostEmbedding.updated_at))
        .join(Post, Post.id == PostEmbedding.post_id)
        .where(Post.island_id == island_id, Post.visibility == "public", Post.status == "published",
               PostEmbedding.model == client.embedding_model())
    ).one()) + (client.embedding_model(),)
    cached = _vector_cache.get(island_id)
    if cached and cached[0] == key:
        return cached[1], cached[2]
    rows = db.execute(base.order_by(PostEmbedding.post_id.desc()).limit(MAX_POSTS)).all()
    ids = [r[0] for r in rows]
    if not rows:
        matrix = np.zeros((0, 0), dtype=np.float32)
    else:
        matrix = np.asarray([json.loads(r[1]) for r in rows], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / np.where(norms == 0, 1.0, norms)
    _vector_cache[island_id] = (key, ids, matrix)
    return ids, matrix


def greedy_groups(sims: np.ndarray, threshold: float, min_size: int, limit: int | None = None) -> list[list[int]]:
    """닮은 글끼리 묶기 (탐욕적 묶음). 돌려주는 각 묶음의 첫 번째가 대표.
    1) 기준 이상으로 닮은 글이 가장 많은 글을 대표로 고른다.
    2) 대표와 닮은 글을 모두 한 묶음에 넣고 목록에서 뺀다.
    3) 남은 글로 반복. 묶음 크기가 min_size보다 작아지면 멈춘다.
    k-means와 달리 묶음 수를 미리 정하지 않아도 되고, 같은 데이터면 늘 같은 결과가 나온다."""
    left = list(range(len(sims)))
    groups: list[list[int]] = []
    while left and (limit is None or len(groups) < limit):
        sub = sims[np.ix_(left, left)] >= threshold
        np.fill_diagonal(sub, False)
        degree = sub.sum(axis=1)
        center = int(np.argmax(degree))
        if degree[center] + 1 < min_size:
            break
        members = [left[center]] + [left[j] for j in np.where(sub[center])[0]]
        groups.append(members)
        taken = set(members)
        left = [i for i in left if i not in taken]
    return groups


def similar_groups(ids: list[int], sims: np.ndarray, threshold: float, posts: dict[int, Post]) -> list[SimilarGroup]:
    out = []
    for members in greedy_groups(sims, threshold, MIN_GROUP, TOP_GROUPS):
        head = posts[ids[members[0]]]
        out.append(SimilarGroup(
            post_id=head.id, title=head.title, topic=head.topic, size=len(members),
            similarity=round(float(sims[members[0], members[1:]].mean()), 3),
        ))
    return out


def bubble_groups(db: Session, island_id: int, post_ids: list[int]) -> dict[int, list[int]]:
    """지도 말풍선 합치기: {대표 글 id: [대표 포함 묶인 글 id들]}. 2개 이상 묶인 것만.
    벡터가 없는 글(아직 임베딩 전)은 따로 남는다."""
    ids, matrix = island_vectors(db, island_id)
    row = {pid: i for i, pid in enumerate(ids)}
    keep = [row[pid] for pid in post_ids if pid in row]
    if len(keep) < 2:
        return {}
    sub = matrix[keep]
    threshold = PAIR_SIMILARITY.get(settings.provider(), 0.58)
    groups = greedy_groups(sub @ sub.T, threshold, min_size=2)
    return {ids[keep[g[0]]]: [ids[keep[i]] for i in g] for g in groups}


def my_resonance(
    me: User, ids: list[int], sims: np.ndarray, threshold: float, posts: dict[int, Post], topics: Counter,
) -> MyResonance | None:
    mine = [i for i, pid in enumerate(ids) if posts[pid].user_id == me.id]
    if not mine:
        return None
    row = max(mine, key=lambda i: posts[ids[i]].created_at)  # 내 가장 최근 고민
    post = posts[ids[row]]
    others = [i for i, pid in enumerate(ids) if posts[pid].user_id != me.id]
    close = [i for i in others if sims[row, i] >= threshold]
    # 공동 순위: 나보다 글이 많은 주제 "개수 종류"만 센다 (1,1,1개짜리 주제가 여럿이면 모두 같은 순위)
    mine_count = topics.get(post.topic, 0)
    rank = 1 + len({c for c in topics.values() if c > mine_count}) if mine_count else None
    return MyResonance(
        post_id=post.id, title=post.title, topic=post.topic,
        similar_posts=len(close),
        neighbors=len({posts[ids[i]].user_id for i in close}),
        share=round(len(close) / len(others), 3) if others else 0.0,
        top_similarity=round(float(max(sims[row, i] for i in others)), 3) if others else None,
        topic_rank=rank,
    )


def job_tops(db: Session, cutoff: datetime) -> list[JobTop]:
    rows = db.execute(
        select(Island.id, Island.name, Island.job, Post.topic)
        .select_from(Post).join(Island, Island.id == Post.island_id)
        .where(Post.visibility == "public", Post.status == "published", Island.type == "job", Post.created_at < cutoff)
    ).all()
    by_island: dict[int, tuple[str, str, Counter]] = {}
    for island_id, name, job, topic in rows:
        by_island.setdefault(island_id, (name, job, Counter()))[2][topic] += 1
    out = []
    for island_id, (name, job, counter) in by_island.items():
        total = sum(counter.values())
        topic, count = counter.most_common(1)[0]
        if total >= MIN_POSTS and count >= 2:  # 1개씩 고루 퍼진 섬은 "가장 많은 주제"가 없다
            out.append(JobTop(job=job, island_id=island_id, island_name=name, topic=topic,
                              ratio=round(count / total, 3), posts=total))
    return sorted(out, key=lambda j: -j.posts)


def todays_pair(db: Session, island: Island, me: User, hidden: set[int], now: datetime) -> tuple[PostPick | None, PostPick | None]:
    base = public_posts().where(Post.island_id == island.id, Post.created_at < now)
    if hidden:
        base = base.where(Post.user_id.not_in(hidden))
    ids = base.with_only_columns(Post.id)
    warm = db.execute(
        select(Reaction.post_id, func.count(Reaction.id).label("n"))
        .where(Reaction.post_id.in_(ids), Reaction.created_at >= now - timedelta(days=1), Reaction.created_at < now)
        .group_by(Reaction.post_id).order_by(func.count(Reaction.id).desc(), Reaction.post_id.desc()).limit(1)
    ).first()
    warmest = None
    if warm and warm.n >= MIN_WARM:
        p = db.get(Post, warm.post_id)
        warmest = PostPick(post_id=p.id, title=p.title, topic=p.topic, count=warm.n)
    # 최근 7일 안의 글 중 (지금도) 이웃 댓글이 없는 가장 오래 기다린 글 (내 글은 빼고)
    p = db.scalars(
        base.where(Post.user_id != me.id, Post.created_at >= now - WEEK, ~neighbor_comment_exists())
        .order_by(Post.created_at).limit(1)
    ).first()
    waiting = PostPick(post_id=p.id, title=p.title, topic=p.topic, count=0) if p else None
    return warmest, waiting


def headlines(out: InsightsOut, island: Island) -> list[str]:
    lines = []
    top = [t for t in out.topics if out.topics and t.count == out.topics[0].count]
    if top and top[0].count >= 2:
        names = "'·'".join(t.label for t in top[:2])
        share = ("각 " if len(top) > 1 else "") + f"{pct(top[0].ratio)}%"
        lines.append(f"이 섬에 쌓인 고민 {out.total_posts}개 중 가장 많은 건 '{names}'{copula(top[min(1, len(top) - 1)].label)} ({share}).")
    elif out.topics:
        lines.append(f"이 섬의 고민 {out.total_posts}개는 {out.topic_kinds}가지 주제에 고루 퍼져 있어요.")
    if out.categories:
        c = out.categories[0]
        lines.append(f"고민의 {pct(c.ratio)}%가 '{c.label}' 쪽이에요.")
    if out.rising:
        r = out.rising
        lines.append(f"이번 주엔 '{r.topic}' 고민이 늘었어요 (지난주 {r.last_week}개 → 이번 주 {r.this_week}개).")
    if out.time.busiest and out.time.busiest_count >= 2:
        lines.append(f"고민은 {out.time.busiest}에 가장 많이 올라와요.")
    if out.groups:
        g = out.groups[0]
        lines.append(f"'{g.title}'{with_and(g.title)} 결이 닮은 고민이 {g.size}개 모여 있어요.")
    if out.comfort:
        c = out.comfort[0]
        lines.append(f"가장 많이 바란 위로는 '{c.label}'{copula(c.label)} ({pct(c.ratio)}%).")
    if out.me and out.me.neighbors:
        lines.append(f"내 고민과 닮은 고민을 쓴 이웃이 {out.me.neighbors}명 있어요.")
    here = next((j for j in out.jobs if j.island_id == island.id), None)
    others = [j for j in out.jobs if j.island_id != island.id and (here is None or j.topic != here.topic)]
    if here and others:
        o = others[0]
        lines.append(f"{here.island_name}{topic_mark(here.island_name)} '{here.topic}', "
                     f"{o.island_name}{topic_mark(o.island_name)} '{o.topic}' 고민이 가장 많아요.")
    elif island.type == "common" and len(others) >= 2:
        pairs = ", ".join(f"{j.island_name} '{j.topic}'" for j in others[:3])
        lines.append(f"직무섬마다 가장 많은 고민: {pairs}.")
    return lines


_report_cache: dict[tuple, InsightsOut] = {}
REPORT_CACHE_MAX = 2000


def island_insights(
    db: Session, island: Island, me: User, hidden: set[int], now: datetime | None = None,
) -> InsightsOut:
    """오늘 아침 8시까지 쌓인 글로 만든 리포트. 같은 사람·같은 날·같은 차단 목록이면 저장해 둔 결과를 준다."""
    cutoff, next_at = daily_window(now or datetime.now(timezone.utc))
    key = (island.id, me.id, cutoff, frozenset(hidden))
    if key in _report_cache:
        return _report_cache[key]
    out = _build_insights(db, island, me, hidden, cutoff, next_at)
    if len(_report_cache) >= REPORT_CACHE_MAX:
        _report_cache.clear()  # 날이 바뀌면 어차피 다시 계산하므로 단순하게 비운다
    _report_cache[key] = out
    return out


def _build_insights(
    db: Session, island: Island, me: User, hidden: set[int], cutoff: datetime, next_at: datetime,
) -> InsightsOut:
    now = cutoff  # 아래 계산의 '지금'은 오늘 아침 8시
    stmt = public_posts().where(Post.island_id == island.id, Post.created_at < cutoff)
    if hidden:
        stmt = stmt.where(Post.user_id.not_in(hidden))
    posts = db.scalars(stmt).all()
    total = len(posts)
    topics = Counter(p.topic for p in posts)
    categories = Counter(CATEGORY_OF.get(p.topic, "기타") for p in posts)
    comfort = Counter(p.comfort_type for p in posts)

    by_id = {p.id: p for p in posts}
    ids, matrix = island_vectors(db, island.id)
    keep = [i for i, pid in enumerate(ids) if pid in by_id]  # 차단한 사람 글 등은 뺀다
    ids = [ids[i] for i in keep]
    sims = matrix[keep] @ matrix[keep].T if keep else np.zeros((0, 0), dtype=np.float32)
    threshold = PAIR_SIMILARITY.get(settings.provider(), 0.58)

    out = InsightsOut(
        island_id=island.id, island_name=island.name, enough=total >= MIN_POSTS,
        total_posts=total, week_posts=sum(1 for p in posts if p.created_at >= now - WEEK), headlines=[],
        topics=_shares(topics, total, top=TOP_TOPICS),
        topic_kinds=len(topics),
        categories=_shares(categories, total),
        rising=topic_trend(posts, now),
        time=time_share(posts),
        comfort=_shares(comfort, total, labels=COMFORT_TYPES),
        groups=similar_groups(ids, sims, threshold, by_id) if len(ids) >= MIN_GROUP else [],
        me=my_resonance(me, ids, sims, threshold, by_id, topics),
        jobs=job_tops(db, cutoff),
        warmest=None, waiting=None, as_of=cutoff, next_at=next_at,
    )
    out.warmest, out.waiting = todays_pair(db, island, me, hidden, now)
    if out.enough:
        out.headlines = headlines(out, island)
    return out
