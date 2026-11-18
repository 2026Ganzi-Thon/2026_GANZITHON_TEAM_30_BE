import itertools

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Island

http = TestClient(app, raise_server_exceptions=False)
http.__enter__()

_seq = itertools.count(1)


def email_code(email: str, purpose: str) -> str:
    r = http.post("/auth/email-code", json={"email": email, "purpose": purpose})
    assert r.status_code == 200, r.text
    return r.json()["demo_code"]


def signup(job: str = "개발", years: str | None = "1~3년") -> tuple[dict, int]:
    email = f"member{next(_seq)}@ondo-test.com"
    r = http.post("/auth/signup", json={
        "email": email, "code": email_code(email, "signup"), "job": job, "years": years,
        "character": "tiger", "agree_privacy": True,
    })
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["id"]


def island_id(job: str | None = "개발") -> int:
    with SessionLocal() as db:
        if job is None:
            return db.scalar(select(Island.id).where(Island.type == "common"))
        return db.scalar(select(Island.id).where(Island.job == job))


def write_post(headers: dict, **overrides) -> int:
    body = {
        "island_id": island_id("개발"), "topic": "업무량·스트레스", "title": "야근이 계속돼요",
        "content": "요즘 매일 늦게까지 일해서 너무 지쳐요.", "comfort_type": "empathy",
        "visibility": "public", "show_years": False,
    }
    body.update(overrides)
    r = http.post("/posts", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def post_detail(headers: dict, post_id: int) -> dict:
    r = http.get(f"/posts/{post_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def first_ai_comment(headers: dict, post_id: int) -> dict:
    comments = post_detail(headers, post_id)["comments"]
    return next(c for c in comments if c["is_ai"] and c["parent_id"] is None)
