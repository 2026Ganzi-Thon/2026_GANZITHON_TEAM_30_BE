from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app import config
from app.config import CHARACTERS, COMFORT_TYPES, JOBS, TOPIC_CATEGORIES, YEARS
from app.email_code import issue_code, mark_used, send_code_email, verify_code
from app.database import get_db
from app.deps import get_current_user, get_token_payload
from app.queries import withdraw_user
from app.models import RevokedToken, User
from app.nickname import generate_unique_nickname, is_valid_nickname, nickname_taken
from app.schemas import (
    EmailCodeOut,
    EmailCodeRequest,
    LoginRequest,
    NicknameSuggestion,
    SignupResponse,
    EmailCodeVerify,
    SignupRequest,
    StartOut,
    StartRequest,
    TokenResponse,
    UserResponse,
)
from app.ratelimit import limit_ip
from app.security import create_access_token

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


@router.get("/nickname", response_model=NicknameSuggestion, dependencies=[limit_ip("nickname", 60, 60)])
def suggest_nickname(character: str, db: Session = Depends(get_db)):
    if character not in CHARACTERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"캐릭터는 {list(CHARACTERS)} 중 하나여야 합니다")
    return NicknameSuggestion(nickname=generate_unique_nickname(db, character), character=character)


@router.post("/email-code", response_model=EmailCodeOut, dependencies=[limit_ip("email-code", 5, 600)])
def request_email_code(body: EmailCodeRequest, db: Session = Depends(get_db)):
    """가입·로그인 전에 인증코드를 받는다. demo 모드면 메일 대신 응답에 코드를 담는다."""
    email = body.email.lower()
    user_id = db.scalar(select(User.id).where(User.email == email, User.deleted_at.is_(None)))
    if body.purpose == "signup" and user_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다. 로그인해 주세요")
    if body.purpose == "login" and user_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "가입하지 않은 이메일입니다. 회원가입을 먼저 해 주세요")
    return send_code(db, email, body.purpose)


@router.post("/start", response_model=StartOut, dependencies=[limit_ip("email-code", 5, 600)])
def start_with_email(body: StartRequest, db: Session = Depends(get_db)):
    """이메일 하나로 시작: 가입한 적이 있으면 로그인 코드를, 처음이면 가입 코드를 보낸다.
    FE는 is_new를 보고 코드 입력 뒤 바로 로그인하거나, 직무·캐릭터 고르기로 넘어간다."""
    email = body.email.lower()
    user_id = db.scalar(select(User.id).where(User.email == email, User.deleted_at.is_(None)))
    sent = send_code(db, email, "signup" if user_id is None else "login")
    return StartOut(**sent.model_dump(), is_new=user_id is None)


def send_code(db: Session, email: str, purpose: str) -> EmailCodeOut:
    demo_account = email in config.DEMO_CODE_EMAILS or email.rsplit("@", 1)[-1] in config.DEMO_CODE_DOMAINS
    reveal = demo_account or (
        config.EMAIL_MODE == "demo" and (config.ENV != "production" or purpose == "signup")
    )
    if config.EMAIL_MODE == "demo" and not reveal:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "EMAIL_UNAVAILABLE", "message": "지금은 인증 메일을 보낼 수 없어요. 가입한 기기에서는 로그인 상태가 유지돼요"},
        )

    code = issue_code(db, email, purpose)
    if config.EMAIL_MODE == "smtp" and not demo_account:
        try:
            send_code_email(email, code, purpose)
        except Exception:  # SMTP 연결·인증 실패 등: 코드를 저장하지 않고 알려 준다
            db.rollback()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "인증 메일을 보내지 못했어요. 잠시 뒤 다시 시도해 주세요")
    db.commit()
    return EmailCodeOut(
        expires_in=config.EMAIL_CODE_TTL_SECONDS,
        resend_after=config.EMAIL_CODE_RESEND_SECONDS,
        demo_code=code if reveal else None,
    )


@router.post("/email-code/verify", status_code=status.HTTP_204_NO_CONTENT, dependencies=[limit_ip("auth", 20, 600)])
def check_email_code(body: EmailCodeVerify, db: Session = Depends(get_db)):
    """코드가 맞는지만 확인한다 (소모하지 않음). FE가 인증 단계에서 바로 '인증 완료'를 보여 줄 때 쓴다.
    틀리면 남은 횟수가 줄어든다. 실제 소모는 가입·로그인이 성공할 때."""
    verify_code(db, body.email.lower(), body.purpose, body.code)
    db.commit()  # 틀린 횟수(attempts) 저장


@router.post(
    "/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[limit_ip("auth", 20, 600)],
)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    email = body.email.lower() 

    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다")

    if body.nickname:
        if not is_valid_nickname(body.nickname, body.character):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "닉네임은 추천받은 형식(형용사 + 선택한 동물 + 4자리 숫자)이어야 합니다")
        if nickname_taken(db, body.nickname):
            raise HTTPException(status.HTTP_409_CONFLICT, "이미 사용 중인 닉네임입니다. 다시 뽑아 주세요")
        nickname = body.nickname
    else:
        nickname = generate_unique_nickname(db, body.character)

    # 다른 검사를 다 통과한 뒤 코드를 확인한다 (닉네임 중복 등으로 실패해도 코드를 다시 받지 않게)
    email_code = verify_code(db, email, "signup", body.code)
    mark_used(email_code)  # 아래 commit과 함께 저장 → 가입이 성공해야 코드가 소모된다
    user = User(
        email=email,
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
    profile = UserResponse.model_validate(user).model_dump()
    return SignupResponse(**profile, access_token=create_access_token(user.id, body.remember))


@router.post("/login", response_model=TokenResponse, dependencies=[limit_ip("auth", 20, 600)])
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """회사 이메일 + 그 메일로 받은 인증코드로 로그인한다 (비밀번호 없음)."""
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or user.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "가입한 회사 이메일을 확인해 주세요")
    mark_used(verify_code(db, user.email, "login", body.code))
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id, body.remember))

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
