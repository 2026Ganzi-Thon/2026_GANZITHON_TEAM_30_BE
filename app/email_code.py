"""이메일 인증코드 발급·확인·발송.

흐름: POST /auth/email-code → 6자리 코드 발급(해시로 저장) → 메일 발송(또는 demo면 응답에 코드)
     → 가입·로그인 요청의 code를 verify_code로 확인 → 성공하면 호출한 쪽이 used_at을 찍고 commit
"""
import hashlib
import hmac
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import config
from app.models import EmailCode

INVALID_CODE = HTTPException(status.HTTP_400_BAD_REQUEST, "인증코드가 올바르지 않거나 만료됐어요. 다시 받아 주세요")


def _hash(email: str, purpose: str, code: str) -> str:
    """SECRET_KEY로 HMAC 해시. DB가 유출돼도 6자리 코드를 바로 알 수 없게 한다."""
    msg = f"{email}:{purpose}:{code}".encode()
    return hmac.new(config.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def issue_code(db: Session, email: str, purpose: str) -> str:
    """새 코드를 만들고 이전 코드는 지운다. 너무 자주 요청하면 429."""
    now = datetime.now(timezone.utc)
    latest = db.scalar(  # 이미 사용한 코드는 제외 (로그아웃 직후 다시 로그인할 때 막히지 않게)
        select(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.used_at.is_(None))
        .order_by(EmailCode.id.desc())
    )
    if latest is not None:
        wait = config.EMAIL_CODE_RESEND_SECONDS - (now - latest.created_at).total_seconds()
        if wait > 0:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"{int(wait) + 1}초 뒤에 다시 받을 수 있어요")

    code = f"{secrets.randbelow(1_000_000):06d}"  # 000000~999999, 암호학적으로 안전한 난수
    db.execute(delete(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose))
    db.add(EmailCode(
        email=email, purpose=purpose, code_hash=_hash(email, purpose, code),
        expires_at=now + timedelta(seconds=config.EMAIL_CODE_TTL_SECONDS),
    ))
    return code


def verify_code(db: Session, email: str, purpose: str, code: str) -> EmailCode:
    """코드가 맞으면 해당 행을 돌려준다 (used_at은 호출한 쪽이 가입·로그인 성공 시 찍음).
    틀리면 틀린 횟수를 올리고 400. 횟수를 다 쓰면 코드를 폐기한다."""
    row = db.scalar(
        select(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.used_at.is_(None))
        .order_by(EmailCode.id.desc())
    )
    if row is None or row.expires_at < datetime.now(timezone.utc):
        raise INVALID_CODE
    # compare_digest: 비교 시간이 일정해서 타이밍으로 코드를 추측할 수 없다
    if not hmac.compare_digest(row.code_hash, _hash(email, purpose, code)):
        row.attempts += 1
        left = config.EMAIL_CODE_MAX_ATTEMPTS - row.attempts
        if left <= 0:
            db.delete(row)
            db.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "인증코드를 여러 번 틀렸어요. 코드를 다시 받아 주세요")
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"인증코드가 일치하지 않아요 (남은 횟수 {left}번)")
    return row


def mark_used(row: EmailCode) -> None:
    row.used_at = datetime.now(timezone.utc)


def send_code_email(to: str, code: str, purpose: str) -> None:
    """SMTP로 인증 메일 발송. 465면 SSL, 그 외(587)는 STARTTLS."""
    action = "회원가입" if purpose == "signup" else "로그인"
    minutes = config.EMAIL_CODE_TTL_SECONDS // 60
    msg = EmailMessage()
    msg["Subject"] = f"[ON-DO] {action} 인증코드 {code}"
    msg["From"] = config.SMTP_FROM
    msg["To"] = to
    msg.set_content(
        f"ON-DO {action} 인증코드는 {code} 입니다.\n"
        f"{minutes}분 안에 입력해 주세요.\n\n"
        "본인이 요청하지 않았다면 이 메일을 무시해 주세요."
    )
    context = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context, timeout=10) as smtp:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
            smtp.starttls(context=context)
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
