import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import RevokedToken, User
from app.security import decode_access_token


bearer_scheme = HTTPBearer(auto_error=False)

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="로그인이 필요합니다",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> dict:
    """토큰 검증 3단계: ① 헤더에 토큰이 있는가 ② 서명/만료가 유효한가 ③ 로그아웃된 토큰이 아닌가"""
    if credentials is None:
        raise UNAUTHORIZED
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise UNAUTHORIZED
    if db.get(RevokedToken, payload["jti"]) is not None:
        raise UNAUTHORIZED
    return payload


def get_current_user(
    payload: dict = Depends(get_token_payload),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, int(payload["sub"]))
    if user is None or user.deleted_at is not None:
        raise UNAUTHORIZED
    return user
