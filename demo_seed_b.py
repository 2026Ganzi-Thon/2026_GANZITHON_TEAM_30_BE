"""시연용 고민 추가 + 임베딩 (B 담당). A의 demo_seed.py 다음에 실행한다.

    python demo_seed.py --job 개발 --reset
    python demo_seed_b.py               # 고민 추가 + 공개 고민 전체 임베딩
    python demo_seed_b.py --embed-only  # 고민은 그대로 두고 임베딩만 다시

A의 데모 고민에 유사 검색 시연용 고민을 더해 공개 고민이 60개를 넘게 만든다.
"팀장이랑 자꾸 부딪혀요"로 검색하면 직무섬에서 관련 고민이 여러 개 나오도록 구성했다.
AI 키(UPSTAGE_API_KEY 또는 GEMINI_API_KEY)가 있으면 그 임베딩을, 없으면 로컬 임베딩을 쓴다.
"""
import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app import models  # noqa: F401
from app.ai import models as ai_models  # noqa: F401
from app.ai.client import embedding_model
from app.ai.embedding import backfill_embeddings
from app.ai.models import PostEmbedding
from app.database import Base, SessionLocal, engine
from app.models import Comment, Island, Post, User

NOW = datetime.now(timezone.utc)

# (작성자 이메일, 섬("job"=작성자 직무섬 / "common"), 주제, 제목, 본문, 위로 방식, 몇 시간 전, AI 첫 댓글)
EXTRA_POSTS = [
    ("neighbor1@example.com", "job", "직장 내 관계·갈등", "팀장님과 의견이 자꾸 부딪혀요",
     "회의 때마다 제 의견을 말하면 팀장님이 바로 반박하세요. 맞는 말일 때도 있지만 매번 부딪히니까 말하기가 무서워졌어요.",
     "opinion", 7,
     "매번 의견이 부딪히면 말을 꺼내는 것 자체가 부담스러워지죠. 회의 전에 팀장님과 짧게 방향을 먼저 맞춰 보는 건 어떨까요?"),
    ("neighbor3@example.com", "job", "직장 내 관계·갈등", "팀장님이 제 말을 끝까지 안 들어주세요",
     "보고를 하면 중간에 말을 끊고 결론만 말하라고 하세요. 제가 정리를 못 하는 건지 팀장님이 급한 건지 모르겠어요.",
     "experience", 16,
     "말이 자꾸 끊기면 위축되기 쉬워요. 비슷한 상사와 일해 본 이웃들이 많을 거예요. 경험을 나눠 주실 거예요."),
    ("neighbor6@example.com", "job", "직장 내 관계·갈등", "상사와 갈등 후 출근이 두려워요",
     "지난주에 상사와 언성이 높아진 뒤로 서로 말을 안 해요. 아침마다 출근하기가 너무 싫어요.",
     "empathy", 34,
     "갈등이 풀리지 않은 채로 매일 마주치는 건 정말 힘든 일이에요. 그 무거운 마음으로 출근하고 계신 것만으로도 애쓰고 계신 거예요."),
    ("neighbor4@example.com", "job", "업무량·스트레스", "업무가 계속 몰려요",
     "일을 잘한다는 이유로 자꾸 저한테만 일이 몰려요. 거절하면 눈치가 보이고 받으면 야근이에요.",
     "opinion", 11,
     "인정받는 만큼 짐이 무거워지는 건 지치는 일이에요. 지금 맡은 일 목록을 정리해서 우선순위를 함께 정해 달라고 요청해 보는 건 어떨까요?"),
    ("neighbor5@example.com", "job", "성과 압박", "성과 평가 시즌만 되면 잠이 안 와요",
     "올해 목표를 다 못 채운 것 같아서 평가 면담이 너무 걱정돼요. 밤마다 머릿속으로 변명을 연습해요.",
     "empathy", 45,
     "평가를 앞두고 잠까지 설칠 만큼 마음이 무거우셨군요. 그만큼 한 해를 열심히 보내셨다는 뜻이기도 해요."),
    ("neighbor2@example.com", "job", "커리어 성장·역량", "연차는 쌓이는데 실력이 안 느는 것 같아요",
     "같은 일만 반복하다 보니 성장하고 있는지 모르겠어요. 공부를 해야 하는데 퇴근하면 지쳐서 아무것도 못 해요.",
     "experience", 60,
     "성장이 멈춘 것 같은 불안은 많은 분들이 겪어요. 이웃들이 각자 어떻게 이 시기를 지나왔는지 나눠 줄 거예요."),
    ("neighbor3@example.com", "job", "취업·입사 적응", "신입인데 점심시간이 제일 힘들어요",
     "팀 사람들끼리는 다 친한데 저만 대화에 못 끼는 것 같아요. 점심 먹는 시간이 업무보다 더 긴장돼요.",
     "empathy", 80,
     "이미 친한 사이에 끼어드는 건 누구에게나 어려워요. 긴장되는 마음이 자연스러운 거예요. 천천히 가까워져도 괜찮아요."),
    ("neighbor1@example.com", "job", "번아웃·무기력", "주말 내내 누워만 있어요",
     "평일에 너무 지쳐서 주말엔 아무것도 못 하고 누워만 있어요. 그러다 월요일이 오면 또 우울해요.",
     "empathy", 120,
     "평일에 쏟은 힘이 그만큼 컸다는 뜻이에요. 쉬는 것도 회복의 일부예요. 스스로를 너무 탓하지 않으셨으면 해요."),
    ("neighbor6@example.com", "job", "업무 실수", "배포 사고를 내고 자책 중이에요",
     "제가 놓친 부분 때문에 장애가 났어요. 다들 괜찮다고 하는데 저는 계속 그 장면이 떠올라요.",
     "experience", 20,
     "큰 실수 뒤에 마음이 오래 무거운 건 자연스러운 일이에요. 비슷한 일을 겪은 이웃들이 어떻게 털어냈는지 나눠 줄 거예요."),
    ("neighbor4@example.com", "job", "워라밸", "퇴근 후에도 업무 생각이 떠나지 않아요",
     "집에 와서도 내일 할 일을 계속 떠올려요. 쉬어도 쉬는 것 같지 않아요.",
     "opinion", 95,
     "머리가 계속 일을 붙잡고 있으면 정말 피곤하죠. 퇴근 직전에 내일 할 일을 세 줄로 적어 두고 나오는 방법을 써 보는 건 어떨까요?"),
    ("other1@example.com", "common", "직장 내 관계·갈등", "팀장님이랑 성격이 너무 안 맞아요",
     "저는 꼼꼼하게 확인하는 편인데 팀장님은 빨리빨리를 좋아하세요. 사사건건 부딪혀서 다른 팀으로 옮기고 싶을 정도예요.",
     "experience", 9,
     "일하는 속도가 다르면 사소한 일에도 부딪히기 쉬워요. 다른 직무 이웃들도 비슷한 경험을 나눠 줄 거예요."),
    ("other2@example.com", "common", "직장 내 괴롭힘", "선배의 말투가 계속 신경 쓰여요",
     "농담처럼 던지는 말인데 듣고 나면 기분이 상해요. 제가 예민한 건지 헷갈려요.",
     "opinion", 27,
     "기분이 상했다면 그 감정은 충분히 이유가 있어요. 반복된다면 어떤 말이 불편했는지 기록해 두는 것부터 시작해 보는 건 어떨까요?"),
    ("other3@example.com", "common", "미래 불안", "이 일을 언제까지 할 수 있을까요",
     "요즘 AI 이야기가 많아서 제 직무가 사라질까 불안해요. 뭘 준비해야 할지 모르겠어요.",
     "opinion", 38,
     "변화가 빠를수록 불안해지는 건 당연해요. 지금 하는 일 중 사람이 꼭 필요한 부분이 무엇인지 적어 보면 준비할 방향이 보일 수 있어요."),
    ("other4@example.com", "common", "가족·결혼", "일과 육아 사이에서 지쳐요",
     "퇴근하면 바로 육아 출근이에요. 어디에서도 잘하고 있다는 느낌이 안 들어요.",
     "empathy", 56,
     "두 곳에서 모두 애쓰고 계시니 지칠 수밖에 없어요. 잘하고 있다는 느낌이 안 들어도, 매일 버텨 내는 것 자체가 대단한 일이에요."),
    ("other5@example.com", "common", "외로움·고립감", "재택근무 후로 대화할 사람이 없어요",
     "하루 종일 메신저로만 이야기하다 보니 말 한마디 안 하는 날도 있어요. 생각보다 외로워요.",
     "experience", 66,
     "사람 목소리를 듣지 못하는 날이 이어지면 마음이 쉽게 가라앉아요. 재택을 하는 이웃들이 어떻게 지내는지 나눠 줄 거예요."),
    ("other1@example.com", "common", "경제·금전", "월급날이 기다려지지 않아요",
     "월급이 들어와도 카드값이랑 대출이 빠져나가면 남는 게 없어요. 일하는 의미를 잃어가요.",
     "empathy", 88,
     "애써 번 돈이 바로 사라지는 걸 보면 허탈하죠. 그 마음을 털어놓아 주셔서 고마워요."),
    ("other2@example.com", "common", "감정 조절", "회의에서 감정이 얼굴에 다 드러나요",
     "기분이 상하면 표정 관리가 안 돼서 나중에 후회해요. 감정을 숨기는 방법이 있을까요?",
     "opinion", 102,
     "감정이 드러나는 건 그만큼 솔직하다는 뜻이기도 해요. 순간에 숨을 한 번 고르고 메모를 하는 습관을 들여 보는 건 어떨까요?"),
    ("other3@example.com", "common", "건강·생활습관", "야근 때문에 운동을 못 해요",
     "운동을 해야 하는 걸 알지만 퇴근이 늦어서 엄두가 안 나요. 몸이 점점 무거워져요.",
     "experience", 130,
     "시간도 체력도 부족하면 운동은 늘 뒤로 밀리죠. 바쁜 와중에 작게라도 움직이는 이웃들의 방법을 나눠 줄 거예요."),
]


def main(embed_only: bool) -> None:
    Base.metadata.create_all(bind=engine)  # post_embeddings 테이블이 없으면 만든다

    with SessionLocal() as db:
        if not embed_only:
            if db.scalar(select(Post.id).where(Post.title == EXTRA_POSTS[0][3])):
                print("시연용 고민이 이미 있습니다. 임베딩만 다시 합니다.")
            else:
                users = {u.email: u for u in db.scalars(select(User))}
                if "demo@example.com" not in users:
                    raise SystemExit("먼저 python demo_seed.py --job 개발 --reset 을 실행하세요.")
                common = db.scalar(select(Island).where(Island.type == "common"))
                job_islands = {i.job: i for i in db.scalars(select(Island).where(Island.type == "job"))}

                for email, where, topic, title, content, comfort, hours, ai_text in EXTRA_POSTS:
                    writer = users[email]
                    when = NOW - timedelta(hours=hours)
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
                db.commit()
                print(f"시연용 고민 {len(EXTRA_POSTS)}개 추가")

        # demo_seed.py --reset 이 posts를 새로 만들면 예전 벡터가 남아 있을 수 있어 모두 새로 만든다.
        db.execute(delete(PostEmbedding))
        db.commit()
        ok, fail = backfill_embeddings(db, force=True)
        total = db.scalar(select(Post.id).order_by(Post.id.desc()).limit(1))
        print(f"임베딩 완료: {ok}개 성공, {fail}개 실패 (모델: {embedding_model()}, 마지막 글 id: {total})")
        if fail:
            print("※ 실패한 글은 검색에 안 나옵니다. API 키·한도를 확인하고 --embed-only로 다시 실행하세요.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="시연용 고민 추가 + 임베딩 (B)")
    parser.add_argument("--embed-only", action="store_true")
    main(parser.parse_args().embed_only)
