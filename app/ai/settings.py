"""AI 기능 설정 (B 담당). 모두 환경변수로 바꿀 수 있고, .env에 넣으면 자동으로 읽힌다.

AI_PROVIDER
  - auto (기본): UPSTAGE_API_KEY가 있으면 upstage, GEMINI_API_KEY가 있으면 gemini, 둘 다 없으면 local
  - upstage / gemini: 해당 제공사 강제
  - local: 외부 호출 없이 규칙 검사 + 템플릿 댓글 + 로컬 임베딩 (키 없이 개발·테스트할 때)
"""
import os

from dotenv import load_dotenv

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "auto").strip().lower()

UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY", "").strip()
UPSTAGE_BASE_URL = os.getenv("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1").rstrip("/")
UPSTAGE_CHAT_MODEL = os.getenv("UPSTAGE_CHAT_MODEL", "solar-mini4")
UPSTAGE_EMBED_QUERY_MODEL = os.getenv("UPSTAGE_EMBED_QUERY_MODEL", "embedding-query")
UPSTAGE_EMBED_PASSAGE_MODEL = os.getenv("UPSTAGE_EMBED_PASSAGE_MODEL", "embedding-passage")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash-lite")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_EMBED_DIM = int(os.getenv("GEMINI_EMBED_DIM", "768"))

# 게시 전 검사는 사용자가 기다리므로 짧게. 넘기면 규칙 검사 결과만으로 판단한다.
CHECK_TIMEOUT_SECONDS = float(os.getenv("AI_CHECK_TIMEOUT", "5"))
# AI 첫 댓글·임베딩은 백그라운드라 조금 여유 있게.
BACKGROUND_TIMEOUT_SECONDS = float(os.getenv("AI_BACKGROUND_TIMEOUT", "15"))

LOCAL_EMBED_DIM = 512

# 유사도가 이 값보다 낮으면 "결과 없음". 제공사마다 점수 분포가 달라 기본값을 따로 둔다.
_DEFAULT_MIN_SIMILARITY = {"upstage": 0.30, "gemini": 0.55, "local": 0.12}
_MIN_SIMILARITY_OVERRIDE = os.getenv("SEARCH_MIN_SIMILARITY")
SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", "10"))


def provider() -> str:
    if AI_PROVIDER in ("upstage", "gemini", "local"):
        return AI_PROVIDER
    if UPSTAGE_API_KEY:
        return "upstage"
    if GEMINI_API_KEY:
        return "gemini"
    return "local"


def min_similarity() -> float:
    if _MIN_SIMILARITY_OVERRIDE:
        return float(_MIN_SIMILARITY_OVERRIDE)
    return _DEFAULT_MIN_SIMILARITY[provider()]
