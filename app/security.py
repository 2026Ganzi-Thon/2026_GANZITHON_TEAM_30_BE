"""비밀번호 해싱과 JWT 토큰 발급/검증."""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, SECRET_KEY


# ---------- 비밀번호 ----------

def hash_password(password: str) -> str:
    """평문 비밀번호 → bcrypt 해시 문자열. gensalt()가 매번 다른 salt를 만들어
    같은 비밀번호라도 해시값이 달라진다 (레인보우 테이블 공격 방지)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """입력 비밀번호를 저장된 해시와 비교. 해시 안에 salt가 들어 있어서 따로 저장할 필요 없음."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# ---------- JWT ----------

def create_access_token(user_id: int) -> str:
    """로그인 성공 시 발급하는 토큰.
    sub = 누구의 토큰인지(user id), exp = 만료 시각, jti = 토큰 고유 ID(로그아웃 처리용)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """서명과 만료 시간을 검사한 뒤 payload를 돌려준다.
    위조됐거나 만료된 토큰이면 jwt.InvalidTokenError(또는 그 하위 예외)가 발생한다."""
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
