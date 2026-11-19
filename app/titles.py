"""활동 칭호: 위로·고마움·고민 나누기 같은 활동으로 얻는 칭호.

- 칭호마다 (어떤 활동을, 몇 번) 조건이 있다. 활동 수는 DB에서 사람별로 한 번에 묶어 센다.
- 대표 칭호: 직접 고른 칭호(users.title_key)가 아직 유효하면 그것, 아니면 가장 높은 등급의 칭호.
- 12간지 페르소나(공감형·조언형·솔루션형)는 캐릭터로 정해지는 성격이고, 이 칭호는 활동으로 쌓이는 것.
"""
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import Comment, IslandVisit, Post, Reaction, User
from app.schemas import AuthorOut, TitleItem, TitleOut, TitlesOut


@dataclass(frozen=True)
class Title:
    key: str
    icon: str
    name: str
    desc: str
    tier: int  # 1 새싹 · 2 따뜻한 · 3 빛나는 · 4 전설
    stat: str  # 아래 STAT_LABELS 중 하나
    need: int


TITLES: list[Title] = [
    Title("first_post", "🫧", "용기 낸 이웃", "이웃들에게 첫 고민을 털어놓았어요", 1, "posts", 1),
    Title("sprout", "🌱", "새싹 이웃", "이웃에게 첫 위로를 건넸어요", 1, "comments", 1),
    Title("traveler", "🧳", "두 섬 여행자", "직무섬과 통합섬을 모두 다녀왔어요", 1, "islands", 2),
    Title("kind", "🤝", "다정한 이웃", "이웃에게 위로를 5번 건넸어요", 2, "comments", 5),
    Title("heart_rich", "💗", "공감 부자", "이웃의 고민 10개에 공감했어요", 2, "reactions", 10),
    Title("honest", "🪶", "솔직한 이웃", "이웃들과 고민을 5번 나눴어요", 2, "posts", 5),
    Title("storyteller", "📖", "그 뒤 이야기꾼", "내 고민에 이야기를 3번 이어 썼어요", 2, "follow_ups", 3),
    Title("thanked", "💌", "고마움을 받은 이웃", "건넨 위로가 처음으로 고마움을 받았어요", 2, "thanks", 1),
    Title("guide", "🗺️", "섬의 길잡이", "서로 다른 고민 10개에 위로를 건넸어요", 3, "helped", 10),
    Title("campfire", "🔥", "모닥불 지킴이", "이웃에게 위로를 15번 건넸어요", 3, "comments", 15),
    Title("shining", "✨", "빛나는 위로꾼", "건넨 위로가 고마움을 3번 받았어요", 3, "thanks", 3),
    Title("lantern", "🏮", "섬의 등불", "이웃에게 위로를 30번 건넸어요", 4, "comments", 30),
    Title("lighthouse", "🌟", "섬의 등대", "건넨 위로가 고마움을 10번 받았어요", 4, "thanks", 10),
]
BY_KEY = {t.key: t for t in TITLES}
TIER_NAMES = {1: "새싹", 2: "따뜻한", 3: "빛나는", 4: "전설"}
STAT_LABELS = {
    "posts": "나눈 고민",
    "comments": "건넨 위로",
    "islands": "다녀온 섬",
    "reactions": "공감",
    "follow_ups": "이어 쓴 이야기",
    "thanks": "받은 고마움",
    "helped": "위로한 고민",
}


def activity_stats(db: Session, user_ids: Iterable[int]) -> dict[int, dict[str, int]]:
    """사람별 활동 수. 사람 수와 상관없이 쿼리는 활동 종류 수(7번)만큼만 나간다."""
    ids = list({i for i in user_ids if i is not None})
    stats = {i: dict.fromkeys(STAT_LABELS, 0) for i in ids}
    if not ids:
        return stats

    def fill(key: str, stmt) -> None:
        for user_id, n in db.execute(stmt).all():
            stats[user_id][key] = n

    target = aliased(Post)
    # 남의 글에 남긴, 지워지거나 가려지지 않은 내 댓글 = 건넨 위로
    given = (
        Comment.user_id.in_(ids), Comment.is_ai.is_(False),
        Comment.deleted_at.is_(None), Comment.hidden_at.is_(None), target.user_id != Comment.user_id,
    )
    base = select(Comment.user_id).join(target, target.id == Comment.post_id)
    fill("comments", base.add_columns(func.count()).where(*given).group_by(Comment.user_id))
    fill("helped", base.add_columns(func.count(func.distinct(Comment.post_id))).where(*given).group_by(Comment.user_id))
    fill("thanks", base.add_columns(func.count()).where(*given, Comment.thanked_at.is_not(None)).group_by(Comment.user_id))
    fill("follow_ups", base.add_columns(func.count()).where(
        Comment.user_id.in_(ids), Comment.is_ai.is_(False), Comment.deleted_at.is_(None),
        target.user_id == Comment.user_id, target.visibility == "public",  # 나만 보기 글의 AI 대화는 빼기
    ).group_by(Comment.user_id))
    # 나만 보기 글은 세지 않는다: 칭호는 남에게 보이므로, 비공개 글을 썼다는 사실이 새어 나가면 안 된다
    fill("posts", select(Post.user_id, func.count()).where(
        Post.user_id.in_(ids), Post.visibility == "public", Post.status == "published",
    ).group_by(Post.user_id))
    fill("reactions", select(Reaction.user_id, func.count()).where(Reaction.user_id.in_(ids)).group_by(Reaction.user_id))
    fill("islands", select(IslandVisit.user_id, func.count()).where(IslandVisit.user_id.in_(ids))
         .group_by(IslandVisit.user_id))
    return stats


def earned(stat: dict[str, int]) -> list[Title]:
    return [t for t in TITLES if stat.get(t.stat, 0) >= t.need]


def pick(stat: dict[str, int], chosen: str | None) -> Title | None:
    """대표 칭호: 고른 칭호가 아직 유효하면 그것, 아니면 가장 높은 등급 (같은 등급이면 더 어려운 것)."""
    have = earned(stat)
    if chosen and BY_KEY.get(chosen) in have:
        return BY_KEY[chosen]
    return max(have, key=lambda t: (t.tier, TITLES.index(t)), default=None)


def title_out(t: Title | None) -> TitleOut | None:
    if t is None:
        return None
    return TitleOut(key=t.key, icon=t.icon, name=t.name, tier=t.tier, tier_name=TIER_NAMES[t.tier], desc=t.desc)


def attach_titles(db: Session, authors: Iterable[AuthorOut | None]) -> None:
    """화면에 나갈 작성자 정보에 대표 칭호를 붙인다 (한 번에 모아서 계산)."""
    authors = [a for a in authors if a is not None]
    if not authors:
        return
    ids = {a.user_id for a in authors}
    stats = activity_stats(db, ids)
    chosen = dict(db.execute(select(User.id, User.title_key).where(User.id.in_(ids), User.deleted_at.is_(None))).all())
    for a in authors:
        if a.user_id in chosen:  # 탈퇴한 이용자는 칭호 없음
            a.title = title_out(pick(stats[a.user_id], chosen[a.user_id]))


def my_titles(db: Session, me: User) -> TitlesOut:
    stat = activity_stats(db, [me.id])[me.id]
    have = set(earned(stat))
    current = pick(stat, me.title_key)
    return TitlesOut(
        current=title_out(current),
        chosen_key=me.title_key if me.title_key in BY_KEY and BY_KEY[me.title_key] in have else None,
        earned_count=len(have),
        items=[
            TitleItem(
                key=t.key, icon=t.icon, name=t.name, desc=t.desc, tier=t.tier, tier_name=TIER_NAMES[t.tier],
                earned=t in have, progress=min(stat.get(t.stat, 0), t.need), need=t.need,
                stat_label=STAT_LABELS[t.stat],
            )
            for t in TITLES
        ],
    )
