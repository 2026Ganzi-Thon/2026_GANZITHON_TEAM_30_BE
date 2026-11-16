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

JOBS = ["개발", "디자인", "기획", "마케팅", "영업", "인사", "재무", "기타"]
YEARS = ["1년 미만", "1~3년", "3~5년", "5~10년", "10년 이상"]

TOPICS = ["업무 적응", "인간관계", "진로·이직", "워라밸", "기타"]

COMFORT_TYPES = {
    "empathy": "공감해주세요",
    "experience": "경험을 나눠주세요",
    "opinion": "의견을 들려주세요",
}

ISLAND_COUNT_DAYS = 7

CHARACTERS = {
    "otter": "수달",
    "fox": "여우",
    "bear": "곰",
    "rabbit": "토끼",
    "cat": "고양이",
    "penguin": "펭귄",
}


LEFT_NICKNAME = '떠난 이용자'
LEFT_CHARACTER = 'left'