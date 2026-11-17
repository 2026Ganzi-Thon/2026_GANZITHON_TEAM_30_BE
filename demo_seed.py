"""발표용 데모 데이터. 실행: python demo_seed.py --job 개발 --reset
--job: 발표 계정의 직무 (직무섬 글은 어떤 직무에도 어울리는 내용)
--reset: 기존 DB의 모든 데이터를 지우고 새로 만든다 (시연 당일 아침에 한 번 실행)
작성 시각은 '실행 시점 기준 N시간 전'이라, 실행 직후에는 항상 7일 고민 수에 잡힌다."""
import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models  # noqa: F401
from app.config import JOBS
from app.database import Base, SessionLocal, engine
from app.models import Comment, Island, Notification, Post, Reaction, User
from app.nickname import generate_unique_nickname
from app.queries import ensure_islands
NOW = datetime.now(timezone.utc)

# key: (이메일, 직무("demo"=발표 직무 / 0·1=발표 직무를 뺀 나머지 직무 순번), 캐릭터, 연차)
USERS = {
    "me": ("demo@example.com", "demo", "rabbit", "1~3년"),
    "j1": ("neighbor1@example.com", "demo", "tiger", "4~6년"),
    "j2": ("neighbor2@example.com", "demo", "ox", "7~10년"),
    "j3": ("neighbor3@example.com", "demo", "sheep", "1년 미만"),
    "j4": ("neighbor4@example.com", "demo", "dog", None),
    "j5": ("neighbor5@example.com", "demo", "dragon", "11년 이상"),
    "j6": ("neighbor6@example.com", "demo", "pig", "1~3년"),
    "c1": ("other1@example.com", 0, "monkey", "4~6년"),
    "c2": ("other2@example.com", 1, "horse", "1~3년"),
    "c3": ("other3@example.com", 0, "rooster", None),
    "c4": ("other4@example.com", 1, "rat", "7~10년"),
    "c5": ("other5@example.com", 0, "lion", "1년 미만"),
    "left": ("left@example.com", 1, "snake", "4~6년"),  # 탈퇴 처리 → "떠난 이용자"
}

# key: (작성자, 섬, 주제, 제목, 본문, 위로 방식, 몇 시간 전, AI 첫 댓글)
POSTS = {
    "p_me": ("me", "job", "직장 내 관계·갈등", "회의 때 의견을 말하기가 어려워요",
             "회의만 들어가면 머릿속이 하얘져요. 할 말을 준비해 가도 분위기에 눌려서 결국 아무 말도 못 하고 나와요. 다들 어떻게 하세요?",
             "empathy", 5,
             "준비까지 해 갔는데 말을 못 하고 나오면 속상하죠. 그만큼 잘하고 싶은 마음이 크다는 뜻이에요. 다음 회의에서는 한 문장만 말해 보는 것부터 시작해도 충분해요."),
    "p_j1a": ("j1", "job", "워라밸", "야근이 당연한 분위기가 힘들어요",
              "팀 전체가 늦게까지 남아 있어서 정시에 퇴근하면 눈치가 보여요. 제 일이 끝나도 자리를 못 뜨겠어요.",
              "opinion", 2,
              "할 일을 마쳤는데도 눈치 때문에 남아 있는 건 정말 지치는 일이에요. 퇴근 전에 오늘 한 일을 짧게 공유하고 나가는 방법을 써 보는 분들도 많아요."),
    "p_j1b": ("j1", "job", "업무 실수", "실수 하나에 하루 종일 마음이 무거워요",
              "작은 실수였는데 계속 생각나서 다른 일이 손에 안 잡혀요. 팀에 폐를 끼친 것 같아요.",
              "empathy", 50,
              "실수를 오래 곱씹는 건 책임감이 강하다는 증거예요. 이미 수습했다면, 오늘은 스스로에게 조금 너그러워져도 괜찮아요."),
    "p_j2a": ("j2", "job", "이직·퇴사", "이직, 지금이 맞는 타이밍일까요",
              "3년째 같은 일만 반복하는 느낌이에요. 이직을 해야 할지, 조금 더 버텨야 할지 모르겠어요.",
              "experience", 9,
              "성장이 멈춘 느낌은 이직을 고민하게 되는 가장 흔한 이유예요. 지금 회사에서 더 배울 수 있는 것과 밖에서 얻고 싶은 것을 나눠 적어 보면 방향이 보일 수 있어요."),
    "p_j2b": ("j2", "job", "직장 내 관계·갈등", "상사의 피드백이 너무 날카로워요",
              "피드백 자체는 맞는 말인데 말투 때문에 매번 상처를 받아요. 제가 너무 예민한 걸까요?",
              "opinion", 75,
              "맞는 말이라도 말투에 상처받는 건 예민해서가 아니에요. 피드백 내용과 감정을 따로 정리해 보면 조금 덜 흔들릴 수 있어요."),
    "p_j3a": ("j3", "job", "취업·입사 적응", "입사 3개월, 아직도 모르는 게 너무 많아요",
              "물어보는 것도 눈치 보이고, 혼자 찾아보면 시간이 너무 오래 걸려요.",
              "experience", 26,
              "3개월이면 모르는 게 많은 게 당연한 시기예요. 질문을 모아서 하루에 한 번 묻는 식으로 하면 부담이 줄어들어요."),
    "p_j3b": ("j3", "job", "진로·직무 적성", "다른 직무로 바꾸고 싶어요",
              "지금 일도 나쁘진 않은데 자꾸 다른 분야가 눈에 들어와요. 직무 전환 해 보신 분 계신가요?",
              "experience", 12,
              "다른 분야가 계속 눈에 들어온다면 한 번쯤 진지하게 알아볼 만한 신호예요. 작은 사이드 프로젝트로 먼저 경험해 보는 것도 방법이에요."),
    "p_j4": ("j4", "job", "워라밸", "주말에도 업무 메신저가 신경 쓰여요",
             "알림을 꺼 두면 불안하고, 켜 두면 쉬는 것 같지가 않아요.",
             "empathy", 30,
             "쉬는 날에도 마음이 회사에 묶여 있으면 정말 피곤하죠. 확인하는 시간을 정해 두는 것만으로도 조금 숨통이 트일 수 있어요."),
    "p_j5": ("j5", "job", "번아웃·무기력", "번아웃이 온 것 같아요",
             "출근길부터 숨이 막히고, 좋아하던 일도 재미가 없어졌어요.",
             "empathy", 96,
             "그동안 정말 많이 애써 왔다는 뜻이에요. 지금은 잘하려고 하기보다 잠깐 멈춰서 쉬는 게 먼저일 수 있어요. 힘들면 전문가의 도움을 받는 것도 괜찮아요."),
    "p_j6": ("j6", "job", "자존감·비교", "동기와 비교하게 돼요",
             "같이 입사한 동기가 먼저 인정받는 걸 보면 제가 뒤처지는 것 같아요.",
             "opinion", 140,
             "비교가 될 때는 내가 얼마나 왔는지가 잘 안 보이죠. 입사 때의 나와 지금의 나를 비교해 보면 분명 달라진 게 있을 거예요."),
    "p_me_c": ("me", "common", "커리어 성장·역량", "첫 연봉 협상, 어떻게 준비하셨어요?",
               "곧 첫 연봉 협상인데 뭘 준비해야 할지 모르겠어요. 다른 직무 분들은 어떻게 하셨나요?",
               "experience", 28,
               "첫 협상은 누구나 긴장돼요. 지난 1년간 한 일과 성과를 숫자로 정리해 두면 이야기를 꺼내기가 훨씬 쉬워져요."),
    "p_c1": ("c1", "common", "직장 내 관계·갈등", "다른 팀과 협업할 때 자꾸 부딪혀요",
             "서로 쓰는 말이 달라서 회의가 길어지기만 해요. 협업 잘하는 팁이 있을까요?",
             "opinion", 3,
             "직무가 다르면 같은 단어도 다르게 이해하곤 해요. 회의 전에 목표와 용어를 한 줄로 맞춰 두면 부딪힘이 줄어들어요."),
    "p_c2": ("c2", "common", "이직·퇴사", "이직 면접에서 퇴사 이유를 어떻게 말하죠?",
             "솔직하게 말하자니 부정적으로 보일 것 같고, 꾸며 말하자니 자신이 없어요.",
             "experience", 20,
             "퇴사 이유는 '무엇이 싫었는지'보다 '무엇을 하고 싶은지'로 바꿔 말하면 솔직하면서도 긍정적으로 전할 수 있어요."),
    "p_c3": ("c3", "common", "워라밸", "야근 수당 없이 야근하는 게 맞나요",
             "포괄임금이라 야근해도 달라지는 게 없어요. 다들 그냥 하시나요?",
             "opinion", 52,
             "당연하게 넘기기 어려운 고민이에요. 근로계약서와 회사 규정을 먼저 확인해 보고, 필요하면 노무 상담을 받아 보는 것도 방법이에요."),
    "p_c4": ("c4", "common", "조직 문화", "재택과 출근이 섞이니 리듬이 깨져요",
             "요일마다 일하는 장소가 달라서 집중이 잘 안 돼요.",
             "empathy", 22,
             "환경이 자주 바뀌면 리듬이 흔들리는 게 당연해요. 장소와 상관없이 하루를 시작하는 작은 습관 하나를 만들어 보세요."),
    "p_c5": ("c5", "common", "외로움·고립감", "회사에서 마음 터놓을 사람이 없어요",
             "점심도 혼자 먹고, 힘든 일이 있어도 털어놓을 곳이 없어요.",
             "empathy", 110,
             "혼자 버티는 시간이 길었겠어요. 여기에 털어놓은 것만으로도 큰 한 걸음이에요. 이곳 사람들이 함께 들어 줄게요."),
    "p_left": ("left", "common", "이직·퇴사", "퇴사하고 나서야 알게 된 것들",
               "막상 나와 보니 회사 밖에서도 할 수 있는 일이 생각보다 많더라고요. 고민 중인 분들께 조금이나마 도움이 되길 바라요.",
               "experience", 72,
               "경험을 나눠 주셔서 고마워요. 같은 고민을 하는 분들께 큰 힘이 될 거예요."),
}

# (글, 댓글 단 사람, 내용, 글 작성 몇 분 후)
COMMENTS = [
    ("p_me", "j2", "저도 그래서 회의 전에 할 말을 메모장에 한 줄로 적어 가요. 그것만 읽어도 훨씬 나아요.", 60),
    ("p_me", "j5", "연차가 쌓여도 회의는 여전히 긴장돼요. 말 안 해도 듣고 있는 것 자체로 충분히 기여하고 있어요.", 180),
    ("p_me_c", "c4", "저는 작년에 한 일을 숫자로 정리해 갔더니 이야기가 훨씬 수월했어요!", 300),
    ("p_j1a", "j4", "저희 팀도 똑같아요ㅠ 먼저 일어나는 사람이 되기로 마음먹었더니 다른 분들도 따라 나가시더라고요.", 40),
    ("p_j2a", "me", "저도 요즘 같은 고민이라 남 일 같지 않아요. 응원할게요!", 120),
    ("p_j2a", "j6", "저는 이직하고 나서 후회 없었어요. 다만 조건은 미리 꼼꼼히 비교해 보세요.", 200),
    ("p_j3a", "j2", "3개월이면 당연해요. 질문 많이 하는 신입이 오히려 더 빨리 늘어요.", 90),
    ("p_j5", "j1", "저도 작년에 번아웃이 왔었어요. 휴가를 길게 쓰고 나서 조금 회복됐어요. 꼭 쉬세요.", 300),
    ("p_c1", "c2", "용어 정리 문서를 하나 만들어 두니 회의 시간이 반으로 줄었어요.", 70),
    ("p_c5", "me", "저도 그런 적 있어요. 여기서라도 자주 이야기 나눠요.", 400),
    ("p_left", "c3", "좋은 이야기 감사합니다. 저도 용기가 생겨요.", 500),
]

# (글, 공감한 사람들)
REACTIONS = [
    ("p_me", ["j1", "j2", "j3", "j5"]),
    ("p_me_c", ["c1", "c4"]),
    ("p_j1a", ["me", "j2", "j4", "j6"]),
    ("p_j1b", ["j3"]),
    ("p_j2a", ["me", "j1", "j3"]),
    ("p_j5", ["j1", "j2", "j4", "j6", "me"]),
    ("p_c1", ["c2", "c3", "c5"]),
    ("p_c5", ["me", "c1", "c4"]),
    ("p_left", ["c2", "c3"]),
]


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def notify(db, post: Post, actor_id: int | None, type: str, when: datetime, presenter_id: int) -> None:
    if actor_id == post.user_id:
        return
    # 발표 계정의 알림만 안 읽음으로 둬서 섬에 빨간 점이 뜨게 한다
    db.add(Notification(
        user_id=post.user_id, type=type, post_id=post.id, actor_id=actor_id,
        is_read=post.user_id != presenter_id, created_at=when,
    ))


def main(job: str, reset: bool) -> None:
    if reset:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        ensure_islands(db)
        if db.scalar(select(User.id).where(User.email == USERS["me"][0])):
            raise SystemExit("데모 데이터가 이미 있습니다. 새로 만들려면 --reset을 붙여 실행하세요.")

        other_jobs = [j for j in JOBS if j != job]
        users: dict[str, User] = {}
        for key, (email, job_ref, character, years) in USERS.items():
            user = User(
                email=email,
                job=job if job_ref == "demo" else other_jobs[job_ref],
                years=years,
                nickname=generate_unique_nickname(db, character),
                character=character,
                privacy_agreed_at=ago(24 * 10),
                created_at=ago(24 * 10),
            )
            db.add(user)
            db.flush()
            users[key] = user

        islands = {i.job: i for i in db.scalars(select(Island).where(Island.type == "job"))}
        common = db.scalar(select(Island).where(Island.type == "common"))
        me = users["me"]

        posts: dict[str, Post] = {}
        for key, (author, where, topic, title, content, comfort, hours, ai_text) in POSTS.items():
            writer = users[author]
            post = Post(
                user_id=writer.id,
                island_id=common.id if where == "common" else islands[writer.job].id,
                topic=topic, title=title, content=content, comfort_type=comfort,
                visibility="public", status="published", show_years=key == "p_me",
                created_at=ago(hours), updated_at=ago(hours),
            )
            db.add(post)
            db.flush()
            posts[key] = post
            ai_at = ago(hours) + timedelta(minutes=2)
            db.add(Comment(post_id=post.id, user_id=None, content=ai_text, is_ai=True, created_at=ai_at))
            notify(db, post, None, "comment", ai_at, me.id)

        for key, actor, content, minutes in COMMENTS:
            post = posts[key]
            when = post.created_at + timedelta(minutes=minutes)
            db.add(Comment(post_id=post.id, user_id=users[actor].id, content=content, created_at=when))
            notify(db, post, users[actor].id, "comment", when, me.id)

        for key, actors in REACTIONS:
            post = posts[key]
            for i, actor in enumerate(actors):
                when = post.created_at + timedelta(minutes=30 + i * 15)
                db.add(Reaction(post_id=post.id, user_id=users[actor].id, created_at=when))
                notify(db, post, users[actor].id, "reaction", when, me.id)

        db.add(Post(
            user_id=me.id, island_id=islands[job].id, topic="불안·걱정", title="아무에게도 말 못 한 이야기",
            content="요즘 회사 가는 게 조금 무서워요. 아직 누구에게도 말하지 못해서 여기에만 적어 둬요.",
            comfort_type="empathy", visibility="private", status="published",
            created_at=ago(40), updated_at=ago(40),
        ))

        left = users["left"]
        left.email = f"left-{left.id}@deleted.invalid"
        left.nickname = f"left-{left.id}"
        left.years = None
        left.deleted_at = ago(24)

        db.commit()

    print(f"데모 데이터 생성 완료 (발표 직무: {job}섬 + 통합섬)")
    print(f"발표 계정: {USERS['me'][0]} (이메일 + 인증코드, EMAIL_MODE=demo면 체험용 코드 표시)")
    print("이웃 계정: neighbor1~6@example.com, other1~5@example.com")
    print("검색 시연 키워드: 야근, 이직, 상사, 번아웃")
    print("욕설 차단 시연: 댓글에 금칙어를 넣어 보세요 (B의 check_text 기준)")
    print("※ 비슷한 고민 검색은 B의 임베딩 생성이 따로 필요합니다")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="발표용 데모 데이터 생성")
    parser.add_argument("--job", default="개발", choices=JOBS)
    parser.add_argument("--reset", action="store_true", help="기존 데이터를 모두 지우고 새로 만든다")
    args = parser.parse_args()
    main(args.job, args.reset)
