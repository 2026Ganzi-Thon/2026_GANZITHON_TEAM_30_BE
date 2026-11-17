"""임베딩 embed + 저장·삭제 (B 담당)."""
import hashlib
import logging
import re

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai import client, settings
from app.ai.check import mask_personal_info
from app.ai.models import PostEmbedding
from app.models import Post
from app.queries import public_posts

log = logging.getLogger("app.ai")


def _local_embed(text: str) -> list[float]:
    """키 없이도 검색이 돌아가게 하는 대체 임베딩: 글자 2·3-gram을 해시해서 세는 방식.
    의미 이해는 못 하지만 단어가 겹치는 고민은 찾는다 (개발·테스트용)."""
    vec = np.zeros(settings.LOCAL_EMBED_DIM, dtype=np.float32)
    for token in re.findall(r"[0-9A-Za-z가-힣]+", text.lower()):
        grams = [token] if len(token) < 2 else [token[i:i + n] for n in (2, 3) for i in range(len(token) - n + 1)]
        for g in grams:
            h = int.from_bytes(hashlib.md5(g.encode()).digest()[:4], "little")
            vec[h % settings.LOCAL_EMBED_DIM] += 1.0
    norm = float(np.linalg.norm(vec))
    return (vec / norm).tolist() if norm else vec.tolist()


def embed(text: str, task: str = "passage") -> list[float]:
    """task: 저장할 고민은 "passage", 검색어는 "query". 개인정보는 가린 뒤 보낸다.
    AI를 못 쓰면 AIUnavailable을 던진다 (local 모드는 항상 성공)."""
    text = mask_personal_info(text.strip())
    if settings.provider() == "local":
        return _local_embed(text)
    return client.embed_remote([text], task=task, timeout=settings.BACKGROUND_TIMEOUT_SECONDS)[0]


def post_text(post) -> str:
    return f"{post.title}\n{post.content}"


def upsert_post_embedding(db: Session, post) -> bool:
    """고민 벡터를 저장(있으면 교체)한다. 실패하면 False (게시는 그대로 유지)."""
    try:
        vector = embed(post_text(post), task="passage")
    except client.AIUnavailable as e:
        log.warning("post %s 임베딩 실패: %s", post.id, e)
        return False
    row = db.get(PostEmbedding, post.id) or PostEmbedding(post_id=post.id)
    row.model = client.embedding_model()
    row.vector = vector
    db.add(row)
    db.commit()
    return True


def delete_post_embedding(db: Session, post_id: int) -> None:
    db.execute(delete(PostEmbedding).where(PostEmbedding.post_id == post_id))
    db.commit()


def backfill_embeddings(db: Session, *, force: bool = False) -> tuple[int, int]:
    """공개 고민 중 지금 모델의 벡터가 없는 글을 채운다 (시드 데이터용). (성공, 실패) 개수 반환."""
    model = client.embedding_model()
    done = set() if force else set(db.scalars(select(PostEmbedding.post_id).where(PostEmbedding.model == model)))
    ok = fail = 0
    for post in db.scalars(public_posts().order_by(Post.id)).all():
        if post.id in done:
            continue
        if upsert_post_embedding(db, post):
            ok += 1
        else:
            fail += 1
    return ok, fail

