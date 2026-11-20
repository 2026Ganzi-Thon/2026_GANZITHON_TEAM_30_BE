"""섬지기: 섬의 규칙·안전을 맡는 운영자 캐릭터.

- 온도(AI 이웃)는 '위로'를, 섬지기는 '규칙·안전·섬 소식'을 맡는다. 섬지기는 댓글을 달지 않는다.
- 이번 주의 질문: 주(ISO 주차)마다 바뀌고, 직무섬과 통합섬은 서로 다른 질문을 받는다.
- 섬 소식: 최근 7일 동안 섬에서 나눈 고민·위로·고마움·다녀간 이웃 수.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import REPORT_HIDE_THRESHOLD
from app.keeper_lines import keeper_line
from app.models import Comment, Island, IslandVisit, Post
from app.queries import public_posts
from app.schemas import CrisisSupport, KeeperOut, KeeperQuestion, KeeperWeek

KEEPER_NAME = "섬지기"
KST = timezone(timedelta(hours=9))
WEEK_DAYS = 7

# (질문, 이 질문으로 글을 쓸 때 골라 둘 주제)
WEEKLY_QUESTIONS = [
    ("요즘 퇴근하고 나서 마음이 가장 편해지는 순간은 언제인가요?", "워라밸"),
    ("이번 주에 가장 마음이 무거웠던 일은 무엇이었나요?", "업무량·스트레스"),
    ("회사에서 말하지 못하고 삼킨 말이 있다면 여기 놓고 가세요.", "직장 내 관계·갈등"),
    ("요즘 나를 가장 지치게 하는 건 일인가요, 사람인가요?", "번아웃·무기력"),
    ("1년 뒤의 나에게 꼭 묻고 싶은 질문이 있나요?", "미래 불안"),
    ("최근에 했던 실수 중, 아직 마음에 걸리는 게 있나요?", "업무 실수"),
    ("다른 사람과 나를 비교하게 되는 순간은 언제인가요?", "자존감·비교"),
    ("지금 일이 나와 맞는지 고민해 본 적 있나요?", "진로·직무 적성"),
    ("입사 첫 달의 나에게 해 주고 싶은 말이 있나요?", "취업·입사 적응"),
    ("요즘 혼자라고 느껴지는 순간이 있었나요?", "외로움·고립감"),
    ("성과 때문에 쉬어도 마음이 편하지 않았던 적이 있나요?", "성과 압박"),
    ("이직이나 퇴사를 떠올리게 만든 순간이 있었나요?", "이직·퇴사"),
]

# 섬지기 창이 길다는 기획 피드백으로 3줄로 압축 (한 줄 = 한 가지 약속)
KEEPER_RULES = [
    "모두 익명이에요. 회사명·실명·연락처는 쓰지 않아요.",
    "조언보다 먼저, 글쓴이가 바란 위로로 답해요.",
    "불편한 글은 신고해 주세요. 섬지기가 살펴봐요.",  # 몇 번이면 가려지는지는 악용될 수 있어 안 보여줌
]


def greeting(now: datetime) -> tuple[str, str]:
    """(언제인지, 섬지기 한마디): 요일·시간대마다 직장인이 겪는 순간을 짚는다 (app/keeper_lines.py)."""
    return keeper_line(now.astimezone(KST))


def weekly_question(island: Island, now: datetime) -> KeeperQuestion:
    week = now.astimezone(KST).isocalendar().week
    offset = 0 if island.type == "job" else len(WEEKLY_QUESTIONS) // 2  # 두 섬이 같은 주에 다른 질문
    text, topic = WEEKLY_QUESTIONS[(week + offset) % len(WEEKLY_QUESTIONS)]
    return KeeperQuestion(text=text, topic=topic)


def week_news(db: Session, island: Island, now: datetime) -> KeeperWeek:
    since = now - timedelta(days=WEEK_DAYS)
    posts = public_posts().where(Post.island_id == island.id, Post.created_at >= since).subquery()
    topics = Counter(db.scalars(select(posts.c.topic)).all())
    alive = (Comment.deleted_at.is_(None), Comment.hidden_at.is_(None))
    on_island = select(func.count(Comment.id)).join(posts, posts.c.id == Comment.post_id)
    comforts = db.scalar(on_island.where(*alive, Comment.is_ai.is_(False), Comment.created_at >= since)) or 0
    ai_comforts = db.scalar(on_island.where(*alive, Comment.is_ai.is_(True), Comment.created_at >= since)) or 0
    thanks = db.scalar(on_island.where(*alive, Comment.thanked_at >= since)) or 0
    visitors = db.scalar(
        select(func.count(func.distinct(IslandVisit.user_id)))
        .where(IslandVisit.island_id == island.id, IslandVisit.visited_at >= since)
    ) or 0
    return KeeperWeek(
        days=WEEK_DAYS,
        posts=sum(topics.values()),
        comforts=comforts,
        ai_comforts=ai_comforts,
        thanks=thanks,
        visitors=visitors,
        top_topic=topics.most_common(1)[0][0] if topics else None,
    )


def keeper_info(db: Session, island: Island, crisis: dict) -> KeeperOut:
    now = datetime.now(timezone.utc)
    moment, line = greeting(now)
    return KeeperOut(
        name=KEEPER_NAME,
        moment=moment,
        greeting=line,
        question=weekly_question(island, now),
        week=week_news(db, island, now),
        rules=KEEPER_RULES,
        report_hide_threshold=int(REPORT_HIDE_THRESHOLD),
        crisis_support=CrisisSupport(**crisis),
    )
