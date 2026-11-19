"""유사 고민 검색 search_similar (B 담당): 검색어를 벡터로 바꾼 뒤 코사인 유사도 순 정렬 (numpy).
검색어 원문과 검색어 벡터는 저장하지 않는다."""
import json
import re

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import client, settings
from app.ai.embedding import embed
from app.ai.models import PostEmbedding
from app.database import SessionLocal
from app.models import Post

# 짧은 검색어("이직 고민", "회의가 너무 많아")는 임베딩 점수만으로는 낮게 나와 놓치기 쉽다.
# 그래서 검색어의 낱말 조각(2글자)이 제목에 그대로 있으면 점수를 조금 올려 준다.
KEYWORD_BONUS = 0.05  # 겹치는 조각 하나당
KEYWORD_BONUS_MAX = 0.10
# 어미·부사처럼 어디에나 나오는 조각은 겹쳐도 의미가 없으니 뺀다
_COMMON_GRAMS = set(
    "어요 아요 해요 에요 예요 워요 와요 네요 세요 돼요 혀요 려요 져요 해서 어서 아서 너무 진짜 정말 자꾸 계속 "
    "그냥 같아 같은 싶어 있어 없어 했어 하는 해도 이랑 에서 에게 한테 니다 습니 는데 지만".split()
)


def _grams(text: str) -> set[str]:
    out = set()
    for token in re.findall(r"[0-9A-Za-z가-힣]+", text.lower()):
        out.update(token[i:i + 2] for i in range(len(token) - 1))
    return out - _COMMON_GRAMS


def keyword_bonus(query: str, title: str) -> float:
    return min(KEYWORD_BONUS_MAX, KEYWORD_BONUS * len(_grams(query) & _grams(title)))


def search_similar_scored(
    db: Session,
    query: str,
    island_id: int,
    *,
    exclude_user_ids: set[int] | frozenset[int] = frozenset(),
    limit: int | None = None,
    min_similarity: float | None = None,
    title_keywords: bool = False,
) -> list[tuple[int, float]]:
    """(post_id, 유사도) 목록, 유사도 높은 순. 기준값 미만은 버린다 → 빈 목록이면 "결과 없음".
    같은 섬 + 공개·게시됨 + 차단 관계 제외. AI를 못 쓰면 AIUnavailable.
    title_keywords: 사람이 직접 친 짧은 검색어일 때 제목 낱말 일치 점수를 더한다."""
    limit = limit or settings.SEARCH_LIMIT
    threshold = settings.min_similarity() if min_similarity is None else min_similarity

    stmt = (
        select(PostEmbedding.post_id, PostEmbedding.vector_json, Post.title)
        .join(Post, Post.id == PostEmbedding.post_id)
        .where(
            Post.island_id == island_id,
            Post.visibility == "public",
            Post.status == "published",
            PostEmbedding.model == client.embedding_model(),
        )
    )
    if exclude_user_ids:
        stmt = stmt.where(Post.user_id.not_in(exclude_user_ids))
    rows = db.execute(stmt).all()
    if not rows:
        return []

    q = np.asarray(embed(query, task="query"), dtype=np.float32)
    ids = [r[0] for r in rows]
    matrix = np.asarray([json.loads(r[1]) for r in rows], dtype=np.float32)
    if matrix.shape[1] != q.shape[0]:
        return []
    denom = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(q) or 1.0)
    scores = (matrix @ q) / np.where(denom == 0, 1.0, denom)
    if title_keywords:
        scores = scores + np.asarray([keyword_bonus(query, r[2] or "") for r in rows], dtype=np.float32)

    order = np.argsort(-scores)
    return [(ids[i], float(scores[i])) for i in order[:limit] if scores[i] >= threshold]


def search_similar(query: str, island_id: int, db: Session | None = None, **kwargs) -> list[int]:
    """분담표의 연결 함수 형태: post_id 목록 (유사도 순)."""
    if db is not None:
        return [pid for pid, _ in search_similar_scored(db, query, island_id, **kwargs)]
    with SessionLocal() as own:
        return [pid for pid, _ in search_similar_scored(own, query, island_id, **kwargs)]
