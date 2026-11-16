from datetime import datetime, timezone
from sqlalchemy import select
from app import models  
from app.database import Base, SessionLocal, engine
from app.models import Comment, Island, Post, Reaction, User
from app.nickname import generate_unique_nickname
from app.queries import add_ai_comment, create_notification, ensure_islands
from app.security import hash_password

TEST_PASSWORD = "test1234!"

TEST_USERS = [
    {"email": "dev1@example.com", "job": "개발", "years": "1~3년", "character": "otter"},
    {"email": "dev2@example.com", "job": "개발", "years": "3~5년", "character": "bear"},
    {"email": "design1@example.com", "job": "디자인", "years": "1년 미만", "character": "rabbit"},
    {"email": "pm1@example.com", "job": "기획", "years": None, "character": "fox"},  # 연차 선택 안 함
    {"email": "mkt1@example.com", "job": "마케팅", "years": "5~10년", "character": "penguin"},
]

SAMPLE_POSTS = [
    ("dev1@example.com", "job", "인간관계", "코드 리뷰가 너무 무서워요",
     "리뷰 코멘트가 달릴 때마다 제가 부족한 사람 같아서 위축돼요. 다들 어떻게 견디세요?", "empathy"),
    ("dev2@example.com", "job", "업무 적응", "레거시 코드 앞에서 막막해요",
     "입사하자마자 10년 된 코드를 맡았는데 문서가 하나도 없어요.", "experience"),
    ("dev1@example.com", "job", "워라밸", "야근이 당연한 분위기",
     "팀 전체가 늦게까지 남아 있어서 먼저 퇴근하기가 눈치 보여요.", "opinion"),
    ("design1@example.com", "common", "인간관계", "개발자와 소통이 어려워요",
     "디자인 의도를 설명해도 구현이 자꾸 다르게 나와요. 협업 팁이 있을까요?", "opinion"),
    ("pm1@example.com", "common", "진로·이직", "이직을 고민 중이에요",
     "지금 회사에서 3년째인데 성장이 멈춘 느낌이에요.", "experience"),
]


def main():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_islands(db)

        for data in TEST_USERS:
            if db.scalar(select(User.id).where(User.email == data["email"])):
                print("skip  ", data["email"])
                continue
            nickname = generate_unique_nickname(db, data["character"])
            db.add(User(
                **data,
                password_hash=hash_password(TEST_PASSWORD),
                nickname=nickname,
                privacy_agreed_at=datetime.now(timezone.utc),
            ))
            db.commit()
            print("create", data["email"], nickname)

        # 샘플 고민글 (이미 같은 제목이 있으면 건너뜀)
        for email, where, topic, title, content, comfort in SAMPLE_POSTS:
            if db.scalar(select(Post.id).where(Post.title == title)):
                continue
            author = db.scalar(select(User).where(User.email == email))
            if where == "common":
                island = db.scalar(select(Island).where(Island.type == "common"))
            else:
                island = db.scalar(select(Island).where(Island.type == "job", Island.job == author.job))
            db.add(Post(
                user_id=author.id, island_id=island.id, topic=topic, title=title, content=content,
                comfort_type=comfort, visibility="public", status="published",
            ))
            print("post  ", island.name, title)
        db.commit()

        if db.scalar(select(Comment.id)) is None:
            seed_interactions(db)
            print("demo   댓글·공감·알림")
    print(f"\n모든 테스트 계정 비밀번호: {TEST_PASSWORD}")


SAMPLE_COMMENTS = [
    ("코드 리뷰가 너무 무서워요", None, "리뷰가 무섭게 느껴지는 건 그만큼 잘하고 싶은 마음이 크다는 뜻이에요. 지금도 충분히 잘하고 있어요."),
    ("코드 리뷰가 너무 무서워요", "dev2@example.com", "저도 신입 때 똑같았어요. 리뷰는 코드에 대한 거지 사람에 대한 게 아니더라고요."),
    ("레거시 코드 앞에서 막막해요", None, "문서 없는 코드를 맡는 건 누구에게나 막막한 일이에요. 작은 부분부터 천천히 익혀 가도 괜찮아요."),
    ("이직을 고민 중이에요", "design1@example.com", "성장이 멈춘 느낌, 너무 공감돼요. 저는 사이드 프로젝트로 숨통을 틔웠어요."),
]

SAMPLE_REACTIONS = [
    ("코드 리뷰가 너무 무서워요", "dev2@example.com"),
    ("개발자와 소통이 어려워요", "pm1@example.com"),
    ("이직을 고민 중이에요", "mkt1@example.com"),
]


def seed_interactions(db):
    users = {u.email: u for u in db.scalars(select(User))}
    posts = {p.title: p for p in db.scalars(select(Post))}

    for title, email, content in SAMPLE_COMMENTS:
        post = posts[title]
        if email is None:
            add_ai_comment(db, post, content)
            continue
        actor = users[email]
        db.add(Comment(post_id=post.id, user_id=actor.id, content=content))
        create_notification(db, user_id=post.user_id, type="comment", post_id=post.id, actor_id=actor.id)

    for title, email in SAMPLE_REACTIONS:
        post, actor = posts[title], users[email]
        db.add(Reaction(post_id=post.id, user_id=actor.id))
        create_notification(db, user_id=post.user_id, type="reaction", post_id=post.id, actor_id=actor.id)

    dev1 = users["dev1@example.com"]
    dev_island = db.scalar(select(Island).where(Island.type == "job", Island.job == dev1.job))
    db.add(Post(
        user_id=dev1.id, island_id=dev_island.id, topic="기타", title="아무에게도 말 못 한 이야기",
        content="나만 보기로 써 두는 글이에요.", comfort_type="empathy", visibility="private", status="published",
    ))
    db.commit()


if __name__ == "__main__":
    main()
