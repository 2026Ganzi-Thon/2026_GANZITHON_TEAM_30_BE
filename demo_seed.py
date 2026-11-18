"""발표용 데모 데이터. 실행: python demo_seed.py --job 개발 --reset
--job: 발표 계정의 직무 (직무섬 글은 어떤 직무에도 어울리는 내용)
--reset: 기존 DB의 모든 데이터를 지우고 새로 만든다 (시연 당일 아침에 한 번 실행)
작성 시각은 '실행 시점 기준 N시간 전'이라, 실행 직후에는 항상 7일 고민 수에 잡힌다."""
import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models  # noqa: F401
from app.ai import models as ai_models  # noqa: F401
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
    "j7": ("neighbor7@example.com", "demo", "rat", "1년 미만"),
    "j8": ("neighbor8@example.com", "demo", "snake", "4~6년"),
    "j9": ("neighbor9@example.com", "demo", "horse", "1~3년"),
    "j10": ("neighbor10@example.com", "demo", "monkey", None),
    "j11": ("neighbor11@example.com", "demo", "rooster", "7~10년"),
    "j12": ("neighbor12@example.com", "demo", "lion", "1~3년"),
    "j13": ("neighbor13@example.com", "demo", "rabbit", "11년 이상"),
    "j14": ("neighbor14@example.com", "demo", "tiger", "1년 미만"),
    "j15": ("neighbor15@example.com", "demo", "sheep", "4~6년"),
    "o1": ("other6@example.com", 0, "ox", "1~3년"),
    "o2": ("other7@example.com", 0, "dragon", "4~6년"),
    "o3": ("other8@example.com", 0, "dog", "1년 미만"),
    "o4": ("other9@example.com", 0, "pig", None),
    "o5": ("other10@example.com", 0, "snake", "7~10년"),
    "o6": ("other11@example.com", 1, "rabbit", "1~3년"),
    "o7": ("other12@example.com", 1, "sheep", "1년 미만"),
    "o8": ("other13@example.com", 1, "tiger", "4~6년"),
    "o9": ("other14@example.com", 1, "horse", None),
    "o10": ("other15@example.com", 1, "rooster", "11년 이상"),
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
    "p_j7": ("j7", "job", "취업·입사 적응", "첫 프로젝트에서 계속 헤매고 있어요",
             "선배들은 바빠 보여서 묻기가 어렵고, 혼자 해결하려다 시간이 자꾸 늘어나요. 이러다 민폐가 될까 봐 걱정돼요.",
             "experience", 4,
             "처음 맡은 일에서 헤매는 건 자연스러운 과정이에요. 막힌 지점을 한 줄로 정리해 두면 짧게 묻기가 훨씬 쉬워져요."),
    "p_j8": ("j8", "job", "직장 내 관계·갈등", "회의에서 제 의견이 자꾸 묻혀요",
             "회의 때 용기 내서 말을 꺼내도 금방 다른 이야기로 넘어가요. 그 뒤로는 말하기가 점점 망설여져요.",
             "empathy", 1.5,
             "용기 내서 꺼낸 말이 그냥 지나가면 마음이 쪼그라들죠. 그래도 말을 꺼낸 그 순간은 분명 의미 있는 한 걸음이었어요."),
    "p_j9": ("j9", "job", "업무량·스트레스", "마감이 겹쳐서 숨이 막혀요",
             "이번 주에 마감이 세 개나 겹쳤어요. 하나씩 하면 되는 걸 아는데도 머리가 하얘져요.",
             "opinion", 6,
             "한꺼번에 몰리면 무엇부터 해야 할지 막막해지죠. 오늘 꼭 끝낼 일 하나만 고르고 나머지는 잠시 내려놓아 보는 건 어떨까요?"),
    "p_j10": ("j10", "job", "진로·직무 적성", "이 일이 저랑 맞는지 모르겠어요",
              "일은 익숙해졌는데 재미가 하나도 없어요. 다들 이런 마음으로 일하시는 건지 궁금해요.",
              "experience", 14,
              "익숙함과 재미는 다른 문제라서 헷갈릴 수 있어요. 비슷한 시기를 지나온 이웃들이 경험을 나눠 줄 거예요."),
    "p_j11": ("j11", "job", "조직 문화", "팀장이 된 뒤로 외로워졌어요",
              "팀원일 때는 동료들과 편하게 지냈는데, 팀장이 되고 나니 다들 거리를 두는 것 같아요.",
              "empathy", 33,
              "역할이 바뀌면서 관계도 달라지는 건 생각보다 큰 변화예요. 그 낯선 외로움을 혼자 견디고 계셨군요."),
    "p_j12": ("j12", "job", "감정 조절", "작은 일에도 짜증이 확 올라와요",
              "예전엔 넘어갈 일에도 요즘은 짜증이 먼저 나요. 이러다 동료들과 사이가 틀어질까 걱정이에요.",
              "opinion", 18,
              "짜증이 잦아졌다면 그만큼 지쳐 있다는 신호일 수 있어요. 언제 특히 예민해지는지 적어 보면 쉬어야 할 때가 보여요."),
    "p_j13": ("j13", "job", "미래 불안", "연차가 높아질수록 불안해져요",
              "후배들은 빠르게 따라오고, 저는 새로운 걸 배우는 속도가 느려진 것 같아요.",
              "experience", 44,
              "오래 일해 온 만큼 쌓인 경험은 쉽게 따라잡히지 않아요. 같은 고민을 해 본 이웃들의 이야기가 도움이 될 거예요."),
    "p_j14": ("j14", "job", "불안·걱정", "수습 평가가 다가와서 불안해요",
              "다음 달이 수습 종료인데 제가 잘하고 있는지 모르겠어요. 피드백을 받은 적이 거의 없어서 더 불안해요.",
              "empathy", 8,
              "평가를 앞두고 아무 말도 듣지 못하면 더 불안해지죠. 그 마음을 여기 털어놓아 주셔서 고마워요."),
    "p_j15": ("j15", "job", "직장 내 괴롭힘", "회식 자리 농담이 불편했어요",
              "다 같이 웃는 분위기라 아무 말도 못 했는데, 집에 와서도 계속 그 말이 생각나요.",
              "empathy", 26,
              "모두가 웃는 자리에서 불편함을 말하기는 정말 어려워요. 계속 마음에 남는다면 그 감정은 충분히 이유가 있어요."),
    "p_c1j": ("c1", "job", "업무 실수", "보고서 숫자를 잘못 적었어요",
              "이미 공유된 뒤에 발견해서 정정 메일을 보냈어요. 다들 괜찮다고 하지만 신뢰를 잃은 것 같아요.",
              "empathy", 5,
              "스스로 발견하고 바로 바로잡은 건 오히려 믿음을 주는 행동이에요. 오늘은 마음을 조금 내려놓으셔도 괜찮아요."),
    "p_c3j": ("c3", "job", "워라밸", "휴가 쓰는 게 눈치 보여요",
              "연차가 남아 있는데도 바쁜 시기라 말을 꺼내기가 어려워요.",
              "opinion", 21,
              "쉬는 건 당연한 권리인데도 눈치가 보이는 건 흔한 고민이에요. 바쁜 일이 끝나는 날짜에 맞춰 미리 일정을 공유해 보는 건 어떨까요?"),
    "p_c5j": ("c5", "job", "취업·입사 적응", "입사 첫 주, 아무것도 모르겠어요",
              "온보딩 자료는 많은데 어디서부터 봐야 할지 모르겠어요.",
              "experience", 3,
              "첫 주에는 모든 게 낯선 게 당연해요. 먼저 겪어 본 이웃들이 어떻게 적응했는지 나눠 줄 거예요."),
    "p_o1": ("o1", "job", "성과 압박", "목표치가 또 올랐어요",
             "작년 목표도 겨우 채웠는데 올해는 더 올랐어요. 숫자만 보면 숨이 막혀요.",
             "empathy", 12,
             "겨우 해낸 목표가 다시 높아지면 숨이 막힐 만해요. 그동안 버텨 온 것만으로도 정말 애쓰셨어요."),
    "p_o2": ("o2", "job", "커리어 성장·역량", "자격증 공부, 해야 할까요",
             "주변에서 다들 자격증을 따는데 저만 뒤처지는 것 같아요. 실무에 도움이 될지 모르겠어요.",
             "experience", 29,
             "남들이 하니까 불안해지는 마음, 많은 분들이 겪어요. 자격증을 따 본 이웃들이 실제로 어땠는지 나눠 줄 거예요."),
    "p_o3": ("o3", "job", "직장 내 관계·갈등", "동료가 제 아이디어를 자기 것처럼 말해요",
             "회의에서 제가 낸 의견을 동료가 자기 의견처럼 다시 말했어요. 따져야 할지 고민돼요.",
             "opinion", 9,
             "내 생각이 남의 것처럼 지나가면 정말 서운하죠. 다음에는 아이디어를 메일이나 문서로 먼저 남겨 두는 방법도 있어요."),
    "p_o4": ("o4", "job", "번아웃·무기력", "아침에 눈 뜨는 게 힘들어요",
             "알람을 몇 번이나 끄고 겨우 일어나요. 출근 준비하면서 벌써 지쳐요.",
             "empathy", 48,
             "하루를 시작하기도 전에 지친다면 그동안 많이 버텨 오신 거예요. 오늘은 스스로에게 조금 너그러워져도 괜찮아요."),
    "p_o5": ("o5", "job", "이직·퇴사", "퇴사 의사를 언제 말해야 할까요",
             "이직할 곳은 정해졌는데 팀장님께 말을 꺼내기가 너무 어려워요.",
             "experience", 60,
             "좋은 소식인데도 말을 꺼내기는 무겁죠. 먼저 퇴사 이야기를 해 본 이웃들이 경험을 나눠 줄 거예요."),
    "p_c2j": ("c2", "job", "직장 내 관계·갈등", "협업 상대의 메시지가 올 때마다 긴장돼요",
              "말투가 날카로운 분이라 메시지 알림만 떠도 심장이 뛰어요. 답장을 몇 번이나 고쳐 써요.",
              "empathy", 7,
              "알림 하나에도 몸이 먼저 긴장할 만큼 신경이 쓰이셨군요. 그렇게 조심스럽게 답하려는 마음이 느껴져요."),
    "p_c4j": ("c4", "job", "가족·결혼", "결혼 준비와 회사 일 사이에서 지쳐요",
              "평일엔 일, 주말엔 결혼 준비로 쉴 틈이 없어요. 둘 다 잘하고 싶은데 체력이 따라주지 않아요.",
              "empathy", 23,
              "두 가지를 모두 잘 해내고 싶은 마음이 크신 만큼 지치기 쉬워요. 잠깐이라도 아무것도 하지 않는 시간을 챙기셨으면 해요."),
    "p_o6": ("o6", "job", "업무량·스트레스", "갑자기 일정이 당겨졌어요",
             "2주 뒤였던 일정이 다음 주로 당겨졌어요. 팀 전체가 예민해져서 분위기도 무거워요.",
             "opinion", 2,
             "일정이 갑자기 당겨지면 모두가 예민해지죠. 꼭 지켜야 할 것과 줄일 수 있는 것을 팀과 함께 나눠 보는 건 어떨까요?"),
    "p_o7": ("o7", "job", "자존감·비교", "칭찬을 들어도 믿기지 않아요",
             "잘했다는 말을 들어도 운이 좋았을 뿐이라는 생각이 먼저 들어요.",
             "empathy", 15,
             "칭찬이 어색하게 느껴지는 마음, 많은 분들이 겪어요. 운도 실력이 있어야 붙잡을 수 있다는 걸 기억해 주세요."),
    "p_o8": ("o8", "job", "진로·직무 적성", "다른 직무로 옮긴 분 계신가요",
             "지금 직무도 나쁘지 않은데 옆 팀 일이 더 재밌어 보여요. 사내 이동을 해 본 분들 이야기가 궁금해요.",
             "experience", 36,
             "다른 일이 계속 눈에 들어온다면 한번 알아볼 만한 신호예요. 사내 이동을 해 본 이웃들이 이야기를 나눠 줄 거예요."),
    "p_o9": ("o9", "job", "건강·생활습관", "점심을 거르는 날이 많아요",
             "일에 쫓기다 보면 점심을 건너뛰고 오후에 몰아서 군것질을 해요. 몸이 점점 상하는 것 같아요.",
             "opinion", 52,
             "바쁠수록 끼니가 먼저 밀려나죠. 점심시간을 일정표에 회의처럼 넣어 두는 방법을 써 보는 건 어떨까요?"),
    "p_o10": ("o10", "job", "인간관계·갈등", "친한 동료가 퇴사한대요",
              "회사에서 유일하게 마음 터놓던 동료가 다음 달에 떠나요. 벌써부터 허전해요.",
              "empathy", 11,
              "기대던 사람이 떠난다니 벌써 마음 한쪽이 비는 것 같겠어요. 그 허전함을 여기 털어놓아 주셔서 고마워요."),
    "p_j3c": ("j3", "common", "자존감·비교", "주변이 다 잘 되는 것 같아요",
              "SNS를 보면 친구들은 다 승진하고 이직하는데 저만 그대로인 것 같아요.",
              "empathy", 19,
              "남들의 좋은 순간만 보이면 내 자리가 작아 보이죠. 지금의 나도 충분히 애쓰고 있다는 걸 잊지 않으셨으면 해요."),
    "p_j10c": ("j10", "common", "경제·금전", "재테크를 안 하면 뒤처지는 걸까요",
               "다들 투자 이야기를 하는데 저는 적금만 하고 있어요. 이래도 괜찮은지 모르겠어요.",
               "opinion", 40,
               "주변 이야기에 마음이 흔들릴 수 있어요. 나에게 맞는 속도와 방식이 무엇인지부터 정리해 보는 건 어떨까요?"),
    "p_o1c": ("o1", "common", "연애·이별", "바빠서 연애할 시간이 없어요",
              "야근이 잦다 보니 약속을 자꾸 미루게 돼요. 상대에게 미안하고 저도 지쳐요.",
              "empathy", 31,
              "일과 관계 사이에서 미안한 마음까지 안고 계셨군요. 그만큼 상대를 아끼고 있다는 뜻이에요."),
    "p_o6c": ("o6", "common", "조직 문화", "회사 분위기가 갑자기 바뀌었어요",
              "대표가 바뀐 뒤로 규칙이 매주 바뀌어요. 다들 불안해하는 게 느껴져요.",
              "experience", 58,
              "기준이 자주 바뀌면 누구나 불안해져요. 비슷한 변화를 겪어 본 이웃들이 어떻게 지나왔는지 나눠 줄 거예요."),
    "p_j14c": ("j14", "common", "외로움·고립감", "자취하면서 회사만 오가요",
               "퇴근하면 집에 혼자라 하루 대화 상대가 회사 사람뿐이에요.",
               "empathy", 25,
               "집에 돌아와도 이야기 나눌 사람이 없으면 하루가 길게 느껴지죠. 여기서라도 마음을 나눠 주셔서 고마워요."),
    "p_j9c": ("j9", "common", "인간관계·갈등", "친구들과 대화 주제가 달라졌어요",
              "회사 다니고 나서 학창 시절 친구들을 만나면 이야기가 잘 안 통해요. 점점 만남이 줄어들어요.",
              "experience", 34,
              "각자 다른 자리에서 지내다 보면 거리가 느껴질 수 있어요. 비슷한 경험을 한 이웃들이 어떻게 관계를 이어 갔는지 나눠 줄 거예요."),
    "p_o3c": ("o3", "common", "불안·걱정", "일요일 저녁마다 마음이 무거워요",
              "주말이 끝나 간다는 생각만 해도 가슴이 답답해요. 월요일이 오는 게 무서워요.",
              "empathy", 47,
              "일요일 저녁의 그 무거운 기분, 많은 분들이 느끼고 있어요. 오늘 저녁엔 나를 위한 작은 일을 하나 해 보셨으면 해요."),
    "p_o8c": ("o8", "common", "커리어 성장·역량", "사이드 프로젝트를 시작해도 될까요",
              "회사 일만으로는 성장하는 느낌이 없어서 따로 무언가를 해 보고 싶어요. 체력이 버틸지 걱정돼요.",
              "opinion", 64,
              "더 성장하고 싶은 마음이 느껴져요. 처음에는 일주일에 한 시간처럼 작게 정해 두면 부담이 훨씬 줄어들어요."),
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
    ("p_j7", "j3", "저도 첫 프로젝트 때 똑같았어요. 질문을 모아서 하루 한 번 여쭤보니 훨씬 편했어요.", 50),
    ("p_j9", "j11", "마감 세 개를 종이에 적고 오늘 할 것 하나만 동그라미 쳐 보세요. 저는 그게 도움이 됐어요.", 35),
    ("p_j10", "j13", "저도 비슷한 시기가 몇 번 있었어요. 지나고 보니 작은 변화가 답이었어요.", 120),
    ("p_j11", "j5", "팀장이 되면 외로운 게 당연하대요. 다른 팀장님들과 이야기 나누는 자리가 도움이 됐어요.", 200),
    ("p_j12", "j6", "저도 요즘 그래요. 잠을 못 자면 더 심해지더라고요. 잘 쉬고 계신지 궁금해요.", 80),
    ("p_j15", "j9", "그 자리에서 아무 말 못 한 게 당연해요. 불편했다면 불편했던 거예요.", 60),
    ("p_c1j", "c3", "저도 비슷한 실수를 했었는데 바로 정정한 게 오히려 신뢰를 얻었어요.", 45),
    ("p_o1", "o3", "목표를 주 단위로 쪼개 보니 덜 막막했어요. 응원해요!", 90),
    ("p_o3", "c1", "저라면 다음 회의 때 지난번에 말씀드린 것처럼, 으로 시작해 볼 것 같아요.", 30),
    ("p_o4", "o2", "저도 그런 시기가 있었어요. 아침 루틴을 하나만 바꿔 보는 것부터 해 보세요.", 150),
    ("p_c2j", "o7", "저도 답장을 몇 번씩 고쳐 써요. 그 마음 정말 알아요.", 40),
    ("p_o8", "c4", "저 사내 이동 해 봤어요! 옆 팀 분과 커피 한 잔부터 해 보세요.", 100),
    ("p_o10", "o9", "좋은 동료가 떠나는 건 정말 허전하죠. 퇴사 후에도 연락하는 사이가 될 수 있을 거예요.", 70),
    ("p_j3c", "c2", "SNS에는 좋은 순간만 올라오잖아요. 지금도 충분히 잘하고 계세요.", 55),
    ("p_o6c", "j1", "저희 회사도 그랬는데 몇 달 지나니 자리를 잡았어요.", 240),
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


FOLLOW_UPS = {
    "p_me": [
        ("author", "고마워요. 사실 다음 주에 발표도 있어서 더 걱정돼요.", 20),
        ("ai", "발표까지 앞두고 있으면 마음이 더 바쁘겠어요. 첫 문장만 미리 소리 내어 연습해 두면 시작이 훨씬 수월해져요. 어떤 부분이 가장 걱정되세요?", 21),
    ],
}

THANKED = [("p_me", "j2"), ("p_j7", "j3")]

INVITES = [("p_j8", "me"), ("p_j14", "j3")]


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
        ai_roots: dict[str, Comment] = {}
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
            ai_comment = Comment(post_id=post.id, user_id=None, content=ai_text, is_ai=True, created_at=ai_at)
            db.add(ai_comment)
            db.flush()
            ai_roots[key] = ai_comment
            notify(db, post, None, "comment", ai_at, me.id)

        for key, turns in FOLLOW_UPS.items():
            post, root = posts[key], ai_roots[key]
            for speaker, content, minutes in turns:
                when = root.created_at + timedelta(minutes=minutes)
                is_ai = speaker == "ai"
                db.add(Comment(
                    post_id=post.id, user_id=None if is_ai else post.user_id, content=content,
                    is_ai=is_ai, parent_id=root.id, created_at=when,
                ))
                if is_ai:
                    notify(db, post, None, "reply", when, me.id)

        neighbor_comments: dict[tuple[str, str], Comment] = {}
        for key, actor, content, minutes in COMMENTS:
            post = posts[key]
            when = post.created_at + timedelta(minutes=minutes)
            comment = Comment(post_id=post.id, user_id=users[actor].id, content=content, created_at=when)
            db.add(comment)
            neighbor_comments[(key, actor)] = comment
            notify(db, post, users[actor].id, "comment", when, me.id)

        for key, actor in THANKED:
            comment = neighbor_comments[(key, actor)]
            comment.thanked_at = comment.created_at + timedelta(minutes=30)
            db.add(Notification(
                user_id=users[actor].id, type="thanks", post_id=posts[key].id, actor_id=posts[key].user_id,
                is_read=users[actor].id != me.id, created_at=comment.thanked_at,
            ))

        for key, invitee in INVITES:
            post = posts[key]
            db.add(Notification(
                user_id=users[invitee].id, type="invite", post_id=post.id, actor_id=None,
                is_read=users[invitee].id != me.id, created_at=post.created_at + timedelta(minutes=3),
            ))

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
    print(f"이웃 계정: neighbor1~15@example.com, other1~15@example.com (고민 {len(POSTS)}개, 캐릭터 {len(USERS) - 1}명)")
    print("검색 시연 키워드: 야근, 이직, 상사, 번아웃")
    print("욕설 차단 시연: 댓글에 금칙어를 넣어 보세요 (B의 check_text 기준)")
    print("※ 비슷한 고민 검색은 B의 임베딩 생성이 따로 필요합니다")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="발표용 데모 데이터 생성")
    parser.add_argument("--job", default="개발", choices=JOBS)
    parser.add_argument("--reset", action="store_true", help="기존 데이터를 모두 지우고 새로 만든다")
    args = parser.parse_args()
    main(args.job, args.reset)
