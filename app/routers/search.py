"""유사 고민 검색 (B 담당). 단어 필터(LIKE)는 A의 GET /islands/{id}/posts?q= 쪽."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import AIUnavailable
from app.ai.search import search_similar_scored
from app.database import get_db
from app.deps import get_current_user
from app.models import Post, User
from app.queries import blocked_user_ids, get_accessible_island, posts_with_neighbor_comment, visible_comment_counts
from app.ratelimit import limit_ip, limit_user
from app.routers.islands import to_author
from app.schemas import AuthorOut
from app.titles import attach_titles

router = APIRouter(tags=["search"])

# 자주 찾는 키워드 (처음에는 고정 목록). label은 버튼 글자, query는 눌렀을 때 검색할 문장.
KEYWORDS = [
    {"label": "상사와의 관계", "query": "팀장님과 자꾸 부딪혀서 힘들어요"},
    {"label": "번아웃", "query": "아무것도 하기 싫고 너무 지쳐요"},
    {"label": "야근·워라밸", "query": "야근이 많아서 개인 시간이 없어요"},
    {"label": "이직 고민", "query": "이직을 해야 할지 고민돼요"},
    {"label": "업무 실수", "query": "실수를 해서 자책하게 돼요"},
    {"label": "회의 스트레스", "query": "회의 때 의견을 말하기가 어려워요"},
    {"label": "동료와 비교", "query": "동료와 비교돼서 자존감이 떨어져요"},
    {"label": "신입 적응", "query": "입사한 지 얼마 안 돼서 적응이 힘들어요"},
]

EMPTY_MESSAGE = "아직 비슷한 고민이 없어요. 이 마음을 고민으로 남겨 보면 이웃이 함께해 줄 거예요."


class SearchItem(BaseModel):
    id: int
    title: str
    preview: str
    topic: str
    comfort_type: str
    created_at: datetime
    comment_count: int
    author: AuthorOut
    similarity: float
    waiting: bool = False  # 아직 이웃 댓글이 없는 고민 (피드의 '답을 기다리는 고민'과 같은 기준)


class SearchFallback(BaseModel):
    message: str
    keywords: list[dict]
    write_prefill: dict  # "이 내용으로 고민 쓰기" 버튼용 {"content": 검색어}


class SearchOut(BaseModel):
    items: list[SearchItem]
    user_ids: list[int]  # 지도에서 말풍선을 띄울 이웃
    empty: bool
    fallback: SearchFallback | None


@router.get("/search", response_model=SearchOut, dependencies=[limit_user("search", 30, 60)])
def search_posts(
    q: str = Query(..., min_length=2, max_length=200, description="검색 문장 (예: 팀장이랑 자꾸 부딪혀요)"),
    island_id: int = Query(...),
    limit: int = Query(10, ge=1, le=20),
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """섬 안 유사 고민 검색: 검색어를 벡터로 바꿔 코사인 유사도 순으로 정렬.
    기준값보다 낮으면 결과 없음 + 추천 키워드. 검색어는 저장하지 않는다."""
    island = get_accessible_island(db, island_id, me)
    hidden = blocked_user_ids(db, me.id)
    try:
        scored = search_similar_scored(
            db, q.strip(), island.id, exclude_user_ids=hidden, limit=limit, title_keywords=True,
        )
    except AIUnavailable:
        scored = []  # AI 한도 초과 등: 오류 대신 결과 없음 안내

    if not scored:
        return SearchOut(
            items=[], user_ids=[], empty=True,
            fallback=SearchFallback(message=EMPTY_MESSAGE, keywords=KEYWORDS[:3], write_prefill={"content": q.strip()}),
        )

    ids = [pid for pid, _ in scored]
    posts = {p.id: p for p in db.scalars(select(Post).where(Post.id.in_(ids)))}
    authors = {u.id: u for u in db.scalars(select(User).where(User.id.in_({p.user_id for p in posts.values()})))}
    counts = visible_comment_counts(db, ids)
    answered = posts_with_neighbor_comment(db, ids)

    items = [
        SearchItem(
            id=p.id, title=p.title, preview=p.content[:80], topic=p.topic, comfort_type=p.comfort_type,
            created_at=p.created_at, comment_count=counts.get(p.id, 0),
            author=to_author(authors[p.user_id], island), similarity=round(min(score, 1.0), 3),
            waiting=p.id not in answered,
        )
        for pid, score in scored
        if (p := posts.get(pid)) is not None
    ]
    attach_titles(db, [i.author for i in items])
    user_ids = list(dict.fromkeys(i.author.user_id for i in items if authors[i.author.user_id].deleted_at is None))
    return SearchOut(items=items, user_ids=user_ids, empty=False, fallback=None)


@router.get("/search/keywords", dependencies=[limit_ip("keywords", 60, 60)])
def search_keywords():
    """검색 화면의 자주 찾는 키워드 (고정 목록, 로그인 불필요)."""
    return {"keywords": KEYWORDS}
