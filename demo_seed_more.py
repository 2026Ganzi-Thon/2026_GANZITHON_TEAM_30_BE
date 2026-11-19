"""시연용 고민을 더 채운다 (섬 지도에 말풍선이 더 많이 보이게). 실행: python demo_seed_more.py

demo_seed.py → demo_seed_b.py 다음에 쓰는 보충 시드다.
- 이미 데이터가 있는 DB(Neon 등)에도 넣을 수 있도록, 없는 이웃·없는 제목만 추가한다 (여러 번 실행해도 안전).
- 지도에는 이웃마다 최근 글 하나가 말풍선으로 뜨므로, 새 이웃을 만들어 말풍선 수를 늘린다.
- 새 글만 임베딩을 만든다 (비슷한 고민·공명에 바로 잡힘).
- 유리병 편지에 실릴 '그 뒤 이야기'(글쓴이가 덧붙인 답글)와 시드 이웃의 발자국도 채운다.
"""
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models  # noqa: F401
from app.ai import models as ai_models  # noqa: F401
from app.ai.embedding import backfill_embeddings
from app.config import JOBS
from app.database import Base, SessionLocal, engine
from app.models import Comment, Island, IslandVisit, Post, User
from app.nickname import generate_unique_nickname

# (이메일, 직무("demo"=발표 직무 / 0·1=나머지 직무 순번), 캐릭터, 연차)
MORE_USERS = [
    ("neighbor16@example.com", "demo", "ox", "1~3년"),
    ("neighbor17@example.com", "demo", "dog", "4~6년"),
    ("neighbor18@example.com", "demo", "pig", "1년 미만"),
    ("neighbor19@example.com", "demo", "dragon", "7~10년"),
    ("neighbor20@example.com", "demo", "snake", "1~3년"),
    ("neighbor21@example.com", "demo", "rooster", None),
    ("neighbor22@example.com", "demo", "monkey", "4~6년"),
    ("neighbor23@example.com", "demo", "sheep", "1~3년"),
    ("neighbor24@example.com", "demo", "horse", "11년 이상"),
    ("neighbor25@example.com", "demo", "rat", "1년 미만"),
    ("other16@example.com", 0, "lion", "4~6년"),
    ("other17@example.com", 1, "pig", "1~3년"),
]

# (작성자 이메일, 섬("job"/"common"), 주제, 제목, 본문, 위로 방식, 몇 시간 전, AI 첫 댓글)
MORE_POSTS = [
    ("neighbor16@example.com", "job", "직장 내 관계·갈등", "코드 리뷰 코멘트가 너무 아프게 느껴져요",
     "리뷰에서 지적을 받으면 제 실력이 다 드러나는 것 같아서 며칠씩 마음이 무거워요. 다들 아무렇지 않게 받아들이는 것 같은데 저만 이런가 싶어요.",
     "empathy", 3,
     "열심히 만든 결과물에 지적이 달리면 마음이 쓰이는 게 당연해요. 그만큼 잘하고 싶은 마음이 크다는 뜻이에요."),
    ("neighbor17@example.com", "job", "업무량·스트레스", "요청이 갑자기 바뀌어서 다시 처음부터예요",
     "거의 다 만든 기능을 기획이 바뀌었다며 처음부터 다시 하래요. 이번이 벌써 세 번째라 힘이 쭉 빠져요.",
     "opinion", 6,
     "애써 만든 걸 다시 엎으면 허탈하죠. 다음에는 중간 결과를 일찍 공유해서 방향을 먼저 확인받아 보는 건 어떨까요?"),
    ("neighbor18@example.com", "job", "취업·입사 적응", "모르는 걸 물어보기가 눈치 보여요",
     "입사한 지 두 달인데 아직도 모르는 게 많아요. 같은 걸 두 번 물어볼까 봐 혼자 붙잡고 있다가 시간이 다 가요.",
     "experience", 9,
     "처음에는 누구나 모르는 게 많아요. 먼저 그 시기를 지나온 이웃들이 어떻게 물어봤는지 나눠 줄 거예요."),
    ("neighbor19@example.com", "job", "커리어 성장·역량", "관리자 트랙과 실무 사이에서 고민돼요",
     "팀 리드를 맡아 달라는 제안을 받았어요. 사람을 챙기는 일이 맞을지, 계속 손으로 일하고 싶은 건지 모르겠어요.",
     "experience", 14,
     "갈림길에 서면 어느 쪽도 쉽게 고르기 어렵죠. 두 길을 모두 겪어 본 이웃들의 이야기가 도움이 될 거예요."),
    ("neighbor20@example.com", "job", "자존감·비교", "동기와 자꾸 비교하게 돼요",
     "같이 입사한 동기는 벌써 큰 프로젝트를 맡았어요. 축하하면서도 제가 뒤처진 것 같아 마음이 복잡해요.",
     "empathy", 18,
     "축하하는 마음과 조급한 마음이 함께 드는 건 자연스러운 일이에요. 각자의 속도가 다를 뿐이에요."),
    ("neighbor21@example.com", "job", "조직 문화", "회의가 너무 많아서 일할 시간이 없어요",
     "하루에 회의가 다섯 개씩 있어요. 정작 제 일은 저녁에야 시작할 수 있어요.",
     "opinion", 22,
     "회의 사이사이에 일을 끼워 넣다 보면 하루가 금방 지나가죠. 꼭 참석해야 하는 회의만 골라 달라고 요청해 보는 건 어떨까요?"),
    ("neighbor22@example.com", "job", "이직·퇴사", "이직 면접을 몰래 보러 다니는 게 불편해요",
     "반차를 쓰고 면접을 보러 가는데 팀에 거짓말하는 것 같아 마음이 편하지 않아요.",
     "experience", 28,
     "새 길을 찾는 건 잘못이 아니에요. 비슷한 시기를 보낸 이웃들이 어떻게 마음을 정리했는지 나눠 줄 거예요."),
    ("neighbor23@example.com", "job", "불안·걱정", "일요일 저녁만 되면 불안해져요",
     "주말이 끝나 간다는 생각에 일요일 오후부터 가슴이 답답해요. 월요일 아침이 너무 무서워요.",
     "empathy", 33,
     "쉬는 시간이 끝나 간다는 느낌은 정말 무겁죠. 그 불안을 이렇게 꺼내 놓으신 것만으로도 한 걸음이에요."),
    ("neighbor24@example.com", "job", "번아웃·무기력", "10년 차인데 일이 재미없어요",
     "예전에는 새로운 걸 만드는 게 신났는데 요즘은 그냥 버티는 느낌이에요. 쉬어도 의욕이 돌아오지 않아요.",
     "experience", 41,
     "오래 달려온 만큼 지칠 때가 오는 건 자연스러워요. 비슷한 시기를 겪은 이웃들이 어떻게 다시 힘을 냈는지 나눠 줄 거예요."),
    ("neighbor25@example.com", "job", "업무 실수", "첫 업무에서 실수했어요",
     "처음 맡은 일에서 숫자를 잘못 넣어서 다시 해야 했어요. 다들 괜찮다는데 저는 자꾸 떠올라요.",
     "empathy", 50,
     "처음 맡은 일이라 더 잘하고 싶으셨을 거예요. 실수를 바로 알아차리고 고친 것도 충분히 잘한 일이에요."),
    ("neighbor16@example.com", "job", "워라밸", "퇴근 후 메신저 알림이 무서워요",
     "퇴근하고도 메신저가 울리면 심장이 쿵 내려앉아요. 확인 안 하면 불안하고, 확인하면 쉬지 못해요.",
     "opinion", 70,
     "쉬는 시간에도 일이 따라오면 마음이 늘 긴장되죠. 알림을 끄는 시간을 팀과 함께 정해 보는 건 어떨까요?"),
    ("neighbor19@example.com", "job", "직장 내 관계·갈등", "후배에게 피드백 주는 게 어려워요",
     "좋게 말하면 전달이 안 되고, 분명하게 말하면 상처받을까 봐 걱정돼요.",
     "opinion", 90,
     "상대를 배려하면서도 분명하게 전하는 건 정말 어려운 일이에요. 잘한 점 하나와 바꿀 점 하나를 짝지어 말해 보는 건 어떨까요?"),
    ("other16@example.com", "common", "자존감·비교", "SNS 속 다른 사람들 커리어가 부러워요",
     "다들 승진하고 이직하고 잘나가는 것 같아요. 저만 제자리인 것 같아서 앱을 지웠다 깔았다 해요.",
     "empathy", 12,
     "남들의 좋은 순간만 보이면 내 하루가 작게 느껴지기 쉬워요. 지금 버티고 있는 것도 충분히 의미 있는 일이에요."),
    ("other17@example.com", "common", "인간관계·갈등", "의지하던 동료가 떠나서 허전해요",
     "힘들 때마다 이야기 나누던 동료가 다른 회사로 갔어요. 회사에 마음 붙일 곳이 없어진 것 같아요.",
     "empathy", 25,
     "매일 함께하던 사람이 떠나면 빈자리가 크게 느껴지죠. 그 허전함을 충분히 느껴도 괜찮아요."),
    ("other16@example.com", "common", "진로·직무 적성", "지금 직무가 저랑 맞는지 모르겠어요",
     "3년째 하고 있는데 잘하는 건지 좋아하는 건지 헷갈려요. 다른 일을 해 보고 싶다가도 겁이 나요.",
     "experience", 44,
     "익숙해진 만큼 다른 길이 더 궁금해질 때가 있죠. 직무를 바꿔 본 이웃들이 경험을 나눠 줄 거예요."),
    ("other17@example.com", "common", "건강·생활습관", "잠들기 전까지 휴대폰으로 일을 봐요",
     "누워서도 메일과 메신저를 확인하다 보면 새벽이에요. 아침마다 피곤한데 습관이 안 고쳐져요.",
     "opinion", 75,
     "자기 전까지 일을 붙잡고 있으면 몸이 쉬지 못하죠. 잠들기 30분 전에는 휴대폰을 침대에서 먼 곳에 두는 것부터 시작해 보는 건 어떨까요?"),
]

# 유리병 편지에 실릴 '그 뒤 이야기': 글쓴이가 시간이 지나 자기 글에 덧붙인 답글 (제목 → 내용)
FOLLOW_UP_STORIES = {
    "팀장님과 의견이 자꾸 부딪혀요": "댓글 보고 회의 전에 팀장님께 5분만 먼저 이야기드렸어요. 회의에서 덜 부딪히게 됐어요. 고마워요.",
    "배포 사고를 내고 자책 중이에요": "회고 때 제가 놓친 부분을 체크리스트로 만들었더니 팀에서 다 같이 쓰게 됐어요. 이제는 조금 덜 떠올라요.",
    "주말 내내 누워만 있어요": "토요일 오전에 30분만 산책하기로 정했는데, 그것만으로도 월요일이 덜 무거워졌어요.",
    "신입인데 점심시간이 제일 힘들어요": "한 분이 먼저 커피 마시러 가자고 해 주셔서 요즘은 점심이 조금 편해졌어요.",
    "팀장님이랑 성격이 너무 안 맞아요": "서로 일하는 방식을 솔직하게 이야기해 봤어요. 아직 다르지만 덜 답답해요.",
    "재택근무 후로 대화할 사람이 없어요": "일주일에 한 번은 카페에서 일하기로 했어요. 사람 소리만 들려도 훨씬 나아요.",
    "야근 때문에 운동을 못 해요": "퇴근길에 한 정거장 먼저 내려서 걷는 걸로 시작했어요. 작은 것부터 하니까 되네요.",
    "동기와 자꾸 비교하게 돼요": "제가 해낸 일을 한 달 치 적어 봤더니 생각보다 많았어요. 비교가 조금 줄었어요.",
    "SNS 속 다른 사람들 커리어가 부러워요": "앱 알림을 끄고 일주일 지내 봤어요. 마음이 한결 조용해졌어요.",
}

# 시연용 발자국: 시드 이웃들이 최근 몇 시간 안에 섬을 다녀간 것처럼 기록을 새로 고친다
FOOTPRINT_REFRESH_HOURS = 12


def add_follow_up_stories(db, now: datetime) -> int:
    added = 0
    for title, story in FOLLOW_UP_STORIES.items():
        post = db.scalar(select(Post).where(Post.title == title))
        if post is None:
            continue
        has_story = db.scalar(select(Comment.id).where(Comment.post_id == post.id, Comment.user_id == post.user_id))
        if has_story:
            continue
        root = db.scalar(
            select(Comment).where(Comment.post_id == post.id, Comment.is_ai.is_(True), Comment.parent_id.is_(None))
        )
        when = min(post.created_at + timedelta(hours=6), now - timedelta(minutes=30))
        db.add(Comment(post_id=post.id, user_id=post.user_id, content=story,
                       parent_id=root.id if root else None, created_at=when))
        added += 1
    return added


def refresh_footprints(db, now: datetime) -> int:
    """시드 이웃의 발자국이 오래됐으면 최근 몇 시간 안으로 다시 찍는다 (실제 사용자 기록은 건드리지 않음)."""
    rng = random.Random(7)
    seeded = db.scalars(select(User).where(
        User.email.like("%@example.com"), User.email != "demo@example.com", User.deleted_at.is_(None)
    )).all()
    islands = {i.job: i for i in db.scalars(select(Island).where(Island.type == "job"))}
    common = db.scalar(select(Island).where(Island.type == "common"))
    stale = now - timedelta(hours=FOOTPRINT_REFRESH_HOURS)
    refreshed = 0
    for user in seeded:
        for island in (islands.get(user.job), common):
            if island is None or (island is common and rng.random() < 0.5):
                continue
            visit = db.scalar(select(IslandVisit).where(IslandVisit.user_id == user.id, IslandVisit.island_id == island.id))
            if visit is not None and visit.visited_at >= stale:
                continue
            when = now - timedelta(minutes=rng.randint(20, 60 * 10))
            x, y = rng.uniform(15, 85), rng.uniform(20, 85)
            if visit is None:
                db.add(IslandVisit(user_id=user.id, island_id=island.id, x=x, y=y, visited_at=when))
            else:
                visit.x, visit.y, visit.visited_at = x, y, when
            refreshed += 1
    return refreshed


def main() -> None:
    Base.metadata.create_all(bind=engine)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        me = db.scalar(select(User).where(User.email == "demo@example.com"))
        if not me:
            print("발표 계정이 없어 보충 시드를 건너뜁니다. demo_seed.py를 먼저 실행하세요.")
            return
        demo_job = me.job
        other_jobs = [j for j in JOBS if j != demo_job]

        users = {u.email: u for u in db.scalars(select(User))}
        new_users = 0
        for email, job_ref, character, years in MORE_USERS:
            if email in users:
                continue
            user = User(
                email=email,
                job=demo_job if job_ref == "demo" else other_jobs[job_ref],
                years=years,
                nickname=generate_unique_nickname(db, character),
                character=character,
                privacy_agreed_at=now - timedelta(days=10),
                created_at=now - timedelta(days=10),
            )
            db.add(user)
            db.flush()
            users[email] = user
            new_users += 1

        common = db.scalar(select(Island).where(Island.type == "common"))
        job_islands = {i.job: i for i in db.scalars(select(Island).where(Island.type == "job"))}
        existing_titles = set(db.scalars(select(Post.title)))
        new_posts = 0
        for email, where, topic, title, content, comfort, hours, ai_text in MORE_POSTS:
            if title in existing_titles:
                continue
            writer = users[email]
            when = now - timedelta(hours=hours)
            post = Post(
                user_id=writer.id,
                island_id=common.id if where == "common" else job_islands[writer.job].id,
                topic=topic, title=title, content=content, comfort_type=comfort,
                visibility="public", status="published", created_at=when, updated_at=when,
            )
            db.add(post)
            db.flush()
            db.add(Comment(post_id=post.id, user_id=None, content=ai_text, is_ai=True,
                           created_at=when + timedelta(minutes=2)))
            new_posts += 1
        db.flush()
        stories = add_follow_up_stories(db, now)
        footprints = refresh_footprints(db, now)
        db.commit()
        print(f"보충 시드: 이웃 {new_users}명, 고민 {new_posts}개, 그 뒤 이야기 {stories}개, 발자국 {footprints}개")

        if new_posts:
            ok, fail = backfill_embeddings(db)  # 벡터가 없는 글만 채움
            print(f"새 고민 임베딩: {ok}개 성공, {fail}개 실패")


if __name__ == "__main__":
    main()
