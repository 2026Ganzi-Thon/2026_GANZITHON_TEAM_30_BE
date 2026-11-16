"""B 담당 테이블. posts 테이블(A)과 분리해서 서로의 파일을 고칠 일이 없게 한다."""
import json
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostEmbedding(Base):
    """고민 1개당 벡터 1개. 글이 삭제되면 같이 지워진다 (CASCADE).
    벡터는 JSON 문자열로 저장해서 SQLite·PostgreSQL 어디서나 동작한다 (검색은 numpy로)."""

    __tablename__ = "post_embeddings"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(String(100), index=True)  # 다른 모델 벡터끼리 비교하지 않도록
    dim: Mapped[int] = mapped_column(Integer)
    vector_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    @property
    def vector(self) -> list[float]:
        return json.loads(self.vector_json)

    @vector.setter
    def vector(self, value: list[float]) -> None:
        self.vector_json = json.dumps([round(float(x), 6) for x in value])
        self.dim = len(value)
