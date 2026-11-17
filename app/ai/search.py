"""유사 고민 검색 search_similar (B 담당): 검색어를 벡터로 바꾼 뒤 코사인 유사도 순 정렬 (numpy).
검색어 원문과 검색어 벡터는 저장하지 않는다."""
import json

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import client, settings
from app.ai.embedding import embed
from app.ai.models import PostEmbedding
from app.database import SessionLocal
from app.models import Post


def search_similar_scored(
    db: Session,
    query: str,
    island_id: int,
    *,
    exclude_user_ids: set[int] | frozenset[int] = frozenset(),
    limit: int | None = None,
    min_similarity: float | None = None,
) -> list[tuple[int, float]]:
    """(post_id, 유사도) 목록, 유사도 높은 순. 기준값 미만은 버린다 → 빈 목록이면 "결과 없음".
    같은 섬 + 공개·게시됨 + 차단 관계 제외. AI를 못 쓰면 AIUnavailable."""
    limit = limit or settings.SEARCH_LIMIT
    threshold = settings.min_similarity() if min_similarity is None else min_similarity

    stmt = (
        select(PostEmbedding.post_id, PostEmbedding.vector_json)
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

    order = np.argsort(-scores)
    return [(ids[i], float(scores[i])) for i in order[:limit] if scores[i] >= threshold]


def search_similar(query: str, island_id: int, db: Session | None = None, **kwargs) -> list[int]:
    """분담표의 연결 함수 형태: post_id 목록 (유사도 순)."""
    if db is not None:
        return [pid for pid, _ in search_similar_scored(db, query, island_id, **kwargs)]
    with SessionLocal() as own:
        return [pid for pid, _ in search_similar_scored(own, query, island_id, **kwargs)]
