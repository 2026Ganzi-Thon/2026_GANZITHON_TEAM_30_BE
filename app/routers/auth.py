from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.config import CHARACTERS, COMFORT_TYPES, JOBS, TOPIC_CATEGORIES, YEARS
from app.database import get_db
from app.deps import get_current_user, get_token_payload
from app.queries import withdraw_user
from app.models import RevokedToken, User
from app.nickname import generate_unique_nickname, is_valid_nickname, nickname_taken
from app.schemas import (
    LoginRequest,
    NicknameSuggestion,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/options")
def signup_options():
    return {
        "jobs": JOBS,
        "years": YEARS,
        "characters": CHARACTERS,
        "topics": TOPIC_CATEGORIES,
        "comfort_types": COMFORT_TYPES,
    }


@router.get("/nickname", response_model=NicknameSuggestion)
def suggest_nickname(character: str, db: Session = Depends(get_db)):
    if character not in CHARACTERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"캐릭터는 {list(CHARACTERS)} 중 하나여야 합니다")
    return NicknameSuggestion(nickname=generate_unique_nickname(db, character), character=character)


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    email = body.email.lower() 

    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다")

    if body.nickname:
        if not is_valid_nickname(body.nickname, body.character):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "닉네임은 추천받은 형식(형용사 + 선택한 동물)이어야 합니다")
        if nickname_taken(db, body.nickname):
            raise HTTPException(status.HTTP_409_CONFLICT, "이미 사용 중인 닉네임입니다. 다시 뽑아 주세요")
        nickname = body.nickname
    else:
        nickname = generate_unique_nickname(db, body.character)

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        job=body.job,
        years=body.years,  
        nickname=nickname,
        character=body.character,
        privacy_agreed_at=datetime.now(timezone.utc),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
       
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "이메일 또는 닉네임이 이미 사용 중입니다")
    db.refresh(user)  
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or user.deleted_at is not None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다")
    return TokenResponse(access_token=create_access_token(user.id))

@router.delete("/me", status_code= status.HTTP_204_NO_CONTENT)
def withdraw(payload: dict = Depends(get_token_payload),
            user: User= Depends(get_current_user),
            db: Session = Depends(get_db),):
            withdraw_user(db,user,payload)



@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)):
    expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    db.add(RevokedToken(jti=payload["jti"], expires_at=expires_at))
    db.commit()


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user
