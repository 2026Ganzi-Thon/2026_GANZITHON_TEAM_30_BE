"""섬 고민 리포트 API. 계산은 app/insights.py."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.insights import InsightsOut, island_insights
from app.models import User
from app.queries import blocked_user_ids, get_accessible_island
from app.ratelimit import limit_user

router = APIRouter(prefix="/islands", tags=["insights"])


@router.get("/{island_id}/insights", response_model=InsightsOut, dependencies=[limit_user("insights", 20, 60)])
def get_insights(island_id: int, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """섬에 쌓인 공개 고민 분석: 주제 순위·추이, 올라오는 요일·시간대, 바라는 위로,
    비슷한 고민 묶음(벡터 유사도), 내 고민과 닮은 이웃, 직무섬별 비교. 글이 5개 미만이면 enough=false."""
    island = get_accessible_island(db, island_id, me)
    return island_insights(db, island, me, blocked_user_ids(db, me.id))
