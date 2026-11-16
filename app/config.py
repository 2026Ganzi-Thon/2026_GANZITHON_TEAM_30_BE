import os

from dotenv import load_dotenv

load_dotenv()  # 프로젝트 루트의 .env를 환경변수로 읽음 (이미 설정된 값은 덮어쓰지 않음)

ENV = os.getenv("ENV", "dev")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ganzithon.db")

_DEV_SECRET = "dev-only-secret-key-change-me-in-production-32b+"
SECRET_KEY = os.getenv("SECRET_KEY", _DEV_SECRET)
if ENV == "production" and SECRET_KEY == _DEV_SECRET:
    raise RuntimeError("배포 환경에서는 SECRET_KEY 환경변수를 반드시 설정해야 합니다")

# 쉼표로 구분: "https://ondo.vercel.app,http://localhost:5173"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24))  # 1일

# 아래 선택지는 FE 레포(js/app.js, js/village.js)와 같은 값으로 맞춘 것. 바꿀 때는 FE와 함께 바꿀 것.
JOBS = ["디자인", "영업", "개발"]
YEARS = ["1년 미만", "1~3년", "4~6년", "7~10년", "11년 이상"]

# 대분류 → 소분류. 글에는 소분류(TOPICS) 하나를 저장한다.
TOPIC_CATEGORIES = {
    "업무·직장생활": ["업무량·스트레스", "직장 내 관계·갈등", "업무 실수", "성과 압박", "조직 문화", "워라밸", "직장 내 괴롭힘"],
    "진로·성장": ["진로·직무 적성", "이직·퇴사", "커리어 성장·역량", "취업·입사 적응", "미래 불안"],
    "감정·마음": ["번아웃·무기력", "불안·걱정", "외로움·고립감", "자존감·비교", "감정 조절"],
    "관계·일상": ["인간관계·갈등", "연애·이별", "가족·결혼", "경제·금전", "건강·생활습관"],
}
TOPICS = [topic for topics in TOPIC_CATEGORIES.values() for topic in topics]

COMFORT_TYPES = {
    "empathy": "들어주세요",
    "experience": "경험을 나눠주세요",
    "opinion": "함께 생각해주세요",
}

POST_TITLE_MAX = 40
POST_CONTENT_MAX = 1000
COMMENT_MAX = 400

ISLAND_COUNT_DAYS = 7

# 순서가 FE 캐릭터 이미지 번호(assets/characters/0~12.png)와 같다.
CHARACTERS = {
    "rat": "쥐",
    "ox": "소",
    "tiger": "호랑이",
    "rabbit": "토끼",
    "dragon": "용",
    "snake": "뱀",
    "horse": "말",
    "sheep": "양",
    "monkey": "원숭이",
    "rooster": "닭",
    "dog": "개",
    "pig": "돼지",
    "lion": "사자",
}


LEFT_NICKNAME = '떠난 이용자'
LEFT_CHARACTER = 'left'