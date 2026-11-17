"""JWT 토큰 발급/검증. (비밀번호 없이 이메일로 로그인)"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, SECRET_KEY


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
