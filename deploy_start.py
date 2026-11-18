"""배포 서버 시작 스크립트 (Render 등). 실행: python deploy_start.py

Render 무료 플랜은 재시작·재배포 때 디스크(SQLite 파일)가 초기화된다.
그래서 켜질 때 시연 데이터가 없으면 demo_seed → demo_seed_b(임베딩)를 실행한 뒤 서버를 띄운다.
데이터가 이미 있으면 건드리지 않는다 (--reset 하지 않음).
"""
import os
import sys

from sqlalchemy import select

import demo_seed
import demo_seed_b
from app.database import Base, SessionLocal, engine
from app.models import User


def seed_if_empty() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        has_demo = db.scalar(select(User.id).where(User.email == demo_seed.USERS["me"][0]))
    if has_demo:
        print("시연 데이터가 이미 있어 그대로 둡니다.")
        return
    demo_seed.main(os.getenv("DEMO_JOB", "개발"), reset=False)
    try:
        demo_seed_b.main(embed_only=False)
    except Exception as e:  # 임베딩이 실패해도 서버는 띄운다 (검색만 결과가 적어짐)
        print(f"임베딩 실패, 서버는 계속 시작합니다: {e}")


if __name__ == "__main__":
    seed_if_empty()
    sys.stdout.flush()  # execvp가 프로세스를 바꾸기 전에 시드 로그를 내보낸다
    port = os.getenv("PORT", "8000")
    os.execvp("uvicorn", ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port])
