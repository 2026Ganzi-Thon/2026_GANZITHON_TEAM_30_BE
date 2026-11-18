import os

from dotenv import load_dotenv

load_dotenv()  # 프로젝트 루트의 .env를 환경변수로 읽음 (이미 설정된 값은 덮어쓰지 않음)

ENV = os.getenv("ENV", "dev")
POSTGRES_PREFIXES = ("postgres://", "postgresql://")
LOCAL_DB_HOSTS = ("localhost", "127.0.0.1", "::1")


def _db_host(url: str) -> str:
    authority = url.split("://", 1)[-1].split("/", 1)[0].rsplit("@", 1)[-1]
    if authority.startswith("["):
        return authority[1:authority.find("]")]
    return authority.split(":", 1)[0]


def normalize_database_url(url: str) -> str:
    for prefix in POSTGRES_PREFIXES:
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
            break
    if url.startswith("postgresql") and "sslmode=" not in url and _db_host(url) not in LOCAL_DB_HOSTS:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL") or "sqlite:///./ganzithon.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

_DEV_SECRET = "dev-only-secret-key-change-me-in-production-32b+"
SECRET_KEY = os.getenv("SECRET_KEY") or _DEV_SECRET  # 빈 값도 "설정 안 함"으로 본다
if ENV == "production" and SECRET_KEY == _DEV_SECRET:
    raise RuntimeError("배포 환경에서는 SECRET_KEY 환경변수를 반드시 설정해야 합니다")

DEV_ORIGINS = "http://localhost:5500,http://127.0.0.1:5500,http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
CORS_ORIGINS = [o.strip() for o in (os.getenv("CORS_ORIGINS") or DEV_ORIGINS).split(",") if o.strip()]
CORS_ALLOWS_ANY = "*" in CORS_ORIGINS
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") != "0"
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", 64 * 1024))
REPORT_HIDE_THRESHOLD = float(os.getenv("REPORT_HIDE_THRESHOLD", 3))
REPORT_FORCE_HIDE_THRESHOLD = float(os.getenv("REPORT_FORCE_HIDE_THRESHOLD", 6))
REPORT_TRUSTED_ACCOUNT_HOURS = float(os.getenv("REPORT_TRUSTED_ACCOUNT_HOURS", 24))
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}
AI_FOLLOWUP_MAX = int(os.getenv("AI_FOLLOWUP_MAX", 10))
AI_DAILY_REPLY_LIMIT = int(os.getenv("AI_DAILY_REPLY_LIMIT", 30))
INVITE_MAX_PER_POST = int(os.getenv("INVITE_MAX_PER_POST", 3))
INVITE_DAILY_PER_USER = int(os.getenv("INVITE_DAILY_PER_USER", 3))
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
DELETED_COMMENT = '삭제된 댓글입니다'
HIDDEN_COMMENT = '신고가 쌓여 가려진 댓글입니다'
LEFT_CHARACTER = 'left'

# ---------- 이메일 인증코드 ----------
# demo: 메일을 보내지 않고 응답(demo_code)에 코드를 담는다 (시연·개발용)
# smtp: 실제 메일 발송 (Gmail이면 SMTP_HOST=smtp.gmail.com, SMTP_PORT=465, 앱 비밀번호 사용)
EMAIL_MODE = os.getenv("EMAIL_MODE", "demo")
if EMAIL_MODE not in ("demo", "smtp"):
    raise RuntimeError("EMAIL_MODE는 demo 또는 smtp여야 합니다")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))  # 465 = SSL, 587 = STARTTLS
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER
if EMAIL_MODE == "smtp" and not (SMTP_USER and SMTP_PASSWORD):
    raise RuntimeError("EMAIL_MODE=smtp이면 SMTP_USER와 SMTP_PASSWORD를 설정해야 합니다")
DEMO_CODE_DOMAINS = {d.strip().lower() for d in os.getenv("DEMO_CODE_DOMAINS", "example.com").split(",") if d.strip()}

EMAIL_CODE_TTL_SECONDS = 5 * 60  # 코드 유효 시간
EMAIL_CODE_RESEND_SECONDS = 60  # 같은 이메일로 다시 받기까지 기다리는 시간
EMAIL_CODE_MAX_ATTEMPTS = 5  # 이 횟수만큼 틀리면 그 코드는 폐기
