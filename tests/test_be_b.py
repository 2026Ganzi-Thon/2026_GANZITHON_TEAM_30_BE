"""B 담당 기능 검수 테스트. 실행: pytest -q
AI 키 없이(local) 돌고, LLM 응답은 가짜로 바꿔 끼워 확인한다."""
import os
import tempfile

_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_db.name}")
os.environ["AI_PROVIDER"] = "local"
os.environ["EMAIL_MODE"] = "demo"  # 인증코드를 응답(demo_code)으로 받는다

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.ai import client as ai_client, settings as ai_settings  # noqa: E402
from app.ai.check import GUIDE, check_text  # noqa: E402
from app.ai.comment import write_first_comment  # noqa: E402
from app.ai.models import PostEmbedding  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Island, Notification  # noqa: E402

http = TestClient(app)
http.__enter__()  # lifespan: 테이블·섬 생성

_n = 0


def email_code(email: str, purpose: str) -> str:
    """이메일 인증코드 받기 (EMAIL_MODE=demo라 응답에 코드가 온다)."""
    r = http.post("/auth/email-code", json={"email": email, "purpose": purpose})
    assert r.status_code == 200, r.text
    return r.json()["demo_code"]


def user(job="개발", years="1~3년"):
    global _n
    _n += 1
    email = f"u{_n}@test.com"
    r = http.post("/auth/signup", json={
        "email": email, "code": email_code(email, "signup"), "job": job, "years": years,
        "character": "rabbit", "agree_privacy": True,
    })
    assert r.status_code == 201, r.text
    token = http.post("/auth/login", json={"email": email, "code": email_code(email, "login")}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, r.json()["id"]


def island(job=None):
    with SessionLocal() as db:
        if job is None:
            return db.scalar(select(Island.id).where(Island.type == "common"))
        return db.scalar(select(Island.id).where(Island.job == job))


def post_body(**kw):
    body = {
        "island_id": island("개발"), "topic": "직장 내 관계·갈등", "title": "팀장님과 자꾸 부딪혀요",
        "content": "회의 때마다 의견이 부딪혀서 말하기가 무서워요.", "comfort_type": "empathy",
        "visibility": "public", "show_years": True,
    }
    body.update(kw)
    return body


def has_embedding(post_id):
    with SessionLocal() as db:
        return db.get(PostEmbedding, post_id) is not None


# ---------- 2단계: 고민 작성 + 게시 전 검사 ----------

def test_public_post_is_published_listed_embedded_and_gets_ai_comment():
    h, me_id = user()
    r = http.post("/posts", json=post_body(), headers=h)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "published" and data["crisis_support"] is None
    pid = data["id"]

    listed = http.get(f"/islands/{island('개발')}/posts", headers=h).json()
    assert pid in [p["id"] for p in listed["posts"]]

    detail = http.get(f"/posts/{pid}", headers=h).json()
    ai = [c for c in detail["comments"] if c["is_ai"]]
    assert len(ai) == 1 and ai[0]["author"] is None and ai[0]["content"]
    assert detail["years"] == "1~3년"  # 연차 공개 체크
    assert has_embedding(pid)

    with SessionLocal() as db:  # AI 댓글 알림 (actor 없음)
        n = db.scalar(select(Notification).where(Notification.post_id == pid))
        assert n is not None and n.actor_id is None and n.user_id == me_id


@pytest.mark.parametrize("content", [
    "삼성전자 다니는데 팀장님이 너무 힘들어요",
    "연락 주세요 010-1234-5678",
    "메일은 someone@company.com 이에요",
    "(주)온도컴퍼니에서 일하고 있어요",
])
def test_personal_info_or_company_is_rejected_and_not_saved(content):
    h, _ = user()
    before = http.get("/users/me/posts", headers=h).json()
    r = http.post("/posts", json=post_body(content=content), headers=h)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "NEED_EDIT" and detail["reason"] and detail["suggestion"]
    assert detail["issues"] and detail["issues"][0]["type"] == "PERSONAL_INFO"
    assert http.get("/users/me/posts", headers=h).json() == before


def test_profanity_is_rejected():
    h, _ = user()
    r = http.post("/posts", json=post_body(content="그 사람 진짜 병신 같아요"), headers=h)
    assert r.status_code == 422 and r.json()["detail"]["issues"][0]["type"] == "OFFENSIVE"


def test_crisis_post_is_published_with_support_info():
    h, _ = user()
    r = http.post("/posts", json=post_body(content="요즘은 그냥 죽고 싶다는 생각만 들어요"), headers=h)
    assert r.status_code == 201
    support = r.json()["crisis_support"]
    assert {x["phone"] for x in support["resources"]} == {"109", "1577-0199"}
    ai = [c for c in http.get(f"/posts/{r.json()['id']}", headers=h).json()["comments"] if c["is_ai"]]
    assert "109" in ai[0]["content"]


def test_private_post_not_listed_no_ai_comment_no_embedding():
    h, _ = user()
    h2, _ = user()
    r = http.post("/posts", json=post_body(visibility="private", content="삼성전자 얘기도 여기엔 써도 돼요"), headers=h)
    assert r.status_code == 201  # 나만 보기는 본인만 보므로 반려하지 않음
    pid = r.json()["id"]
    assert pid not in [p["id"] for p in http.get(f"/islands/{island('개발')}/posts", headers=h).json()["posts"]]
    assert http.get(f"/posts/{pid}", headers=h).json()["comments"] == []
    assert http.get(f"/posts/{pid}", headers=h2).status_code == 404
    assert not has_embedding(pid)


def test_cannot_post_to_other_job_island_but_can_post_to_common():
    h, _ = user()
    assert http.post("/posts", json=post_body(island_id=island("영업")), headers=h).status_code == 403
    assert http.post("/posts", json=post_body(island_id=island()), headers=h).status_code == 201


def test_validation_errors():
    h, _ = user()
    assert http.post("/posts", json=post_body(topic="없는 주제"), headers=h).status_code == 422
    assert http.post("/posts", json=post_body(comfort_type="hug"), headers=h).status_code == 422
    assert http.post("/posts", json=post_body(title="   "), headers=h).status_code == 422
    assert http.post("/posts", json=post_body(title="가" * 41), headers=h).status_code == 422
    assert http.post("/posts", json=post_body()).status_code == 401


def test_show_years_ignored_when_user_has_no_years():
    h, _ = user(years=None)
    pid = http.post("/posts", json=post_body(show_years=True), headers=h).json()["id"]
    assert http.get(f"/posts/{pid}", headers=h).json()["years"] is None


# ---------- 수정·삭제 ----------

def test_update_rechecks_and_only_owner_can_edit():
    h, _ = user()
    other, _ = user()
    pid = http.post("/posts", json=post_body(), headers=h).json()["id"]

    assert http.patch(f"/posts/{pid}", json={"title": "남이 수정"}, headers=other).status_code == 403
    assert http.delete(f"/posts/{pid}", headers=other).status_code == 403

    bad = http.patch(f"/posts/{pid}", json={"content": "카카오 다니는데요"}, headers=h)
    assert bad.status_code == 422
    assert http.get(f"/posts/{pid}", headers=h).json()["content"].startswith("회의 때마다")

    ok = http.patch(f"/posts/{pid}", json={"content": "고친 내용이에요", "comfort_type": "opinion"}, headers=h)
    assert ok.status_code == 200
    d = http.get(f"/posts/{pid}", headers=h).json()
    assert d["content"] == "고친 내용이에요" and d["comfort_type"] == "opinion"
    assert len([c for c in d["comments"] if c["is_ai"]]) == 1  # 수정해도 AI 댓글은 하나


def test_visibility_switch_updates_embedding_and_ai_comment():
    h, _ = user()
    pid = http.post("/posts", json=post_body(visibility="private"), headers=h).json()["id"]
    assert not has_embedding(pid)

    assert http.patch(f"/posts/{pid}", json={"visibility": "public"}, headers=h).status_code == 200
    assert has_embedding(pid)
    assert any(c["is_ai"] for c in http.get(f"/posts/{pid}", headers=h).json()["comments"])

    assert http.patch(f"/posts/{pid}", json={"visibility": "private"}, headers=h).status_code == 200
    assert not has_embedding(pid)


def test_delete_removes_post_and_embedding():
    h, _ = user()
    pid = http.post("/posts", json=post_body(), headers=h).json()["id"]
    assert http.delete(f"/posts/{pid}", headers=h).status_code == 204
    assert http.get(f"/posts/{pid}", headers=h).status_code == 404
    assert not has_embedding(pid)
    assert http.delete(f"/posts/{pid}", headers=h).status_code == 404


# ---------- 3단계: 댓글 검사 (A의 댓글 API가 B의 check_text 사용) ----------

def test_comment_check_via_a_endpoint():
    h, _ = user()
    h2, _ = user()
    pid = http.post("/posts", json=post_body(), headers=h).json()["id"]
    bad = http.post(f"/posts/{pid}/comments", json={"content": "그걸 왜 참아요 병신같이"}, headers=h2)
    assert bad.status_code == 422 and bad.json()["detail"]["reason"]
    assert http.post(f"/posts/{pid}/comments", json={"content": "많이 힘드셨겠어요"}, headers=h2).status_code == 201


# ---------- 4단계: 유사 검색 ----------

def test_similar_search_block_filter_and_empty_result():
    h, _ = user()
    writer, writer_id = user()
    pid = http.post("/posts", json=post_body(title="팀장님과 의견이 자꾸 부딪혀요"), headers=writer).json()["id"]

    r = http.get("/search", params={"q": "팀장이랑 자꾸 부딪혀요", "island_id": island("개발")}, headers=h).json()
    assert not r["empty"] and pid in [i["id"] for i in r["items"]] and writer_id in r["user_ids"]
    assert r["items"][0]["similarity"] >= r["items"][-1]["similarity"]

    empty = http.get("/search", params={"q": "주식 투자 종목 추천", "island_id": island("개발")}, headers=h).json()
    assert empty["empty"] and empty["fallback"]["keywords"] and empty["fallback"]["write_prefill"]["content"]

    assert http.post("/blocks", json={"user_id": writer_id}, headers=h).status_code == 204
    r = http.get("/search", params={"q": "팀장이랑 자꾸 부딪혀요", "island_id": island("개발")}, headers=h).json()
    assert pid not in [i["id"] for i in r["items"]]

    assert http.get("/search", params={"q": "팀장", "island_id": island("영업")}, headers=h).status_code == 403
    assert http.get("/search/keywords").json()["keywords"]


# ---------- LLM 연동 (가짜 응답) ----------

@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(ai_settings, "AI_PROVIDER", "upstage")
    return monkeypatch


def test_llm_detection_is_merged(llm):
    llm.setattr(ai_client, "chat", lambda *a, **k: (
        '```json\n{"personal_info": {"detected": true, "spans": ["온도전자"], "reason": "회사명", '
        '"suggestion": "회사명 대신 우리 회사라고 써 보세요"}, "offensive": {"detected": false}, '
        '"crisis": {"detected": false}}\n```'
    ))
    r = check_text("온도전자 다니는데 힘들어요", kind="post")
    assert not r.ok and r.checked_by == "llm" and r.issues[0].text == "온도전자" and r.issues[0].start == 0


def test_llm_failure_falls_back_to_rules_and_post_still_publishes(llm):
    def boom(*a, **k):
        raise ai_client.AIUnavailable("http 429")

    llm.setattr(ai_client, "chat", boom)
    llm.setattr(ai_client, "embed_remote", boom)
    r = check_text("팀장님 때문에 힘들어요", kind="post")
    assert r.ok and r.checked_by == "rules"
    assert not check_text("010-1111-2222", kind="post").ok

    h, _ = user()
    res = http.post("/posts", json=post_body(), headers=h)
    assert res.status_code == 201  # 429여도 게시는 된다
    ai = [c for c in http.get(f"/posts/{res.json()['id']}", headers=h).json()["comments"] if c["is_ai"]]
    assert ai and ai[0]["content"]  # 기본 위로 문장


def test_first_comment_uses_llm_and_adds_hotline_for_crisis(llm):
    llm.setattr(ai_client, "chat", lambda *a, **k: '"정말 많이 힘드셨겠어요. 혼자 견디지 않으셔도 돼요."')

    class P:
        title, content, comfort_type, topic = "제목", "다 끝내고 싶어요", "empathy", "번아웃·무기력"

    text = write_first_comment(P, crisis=True)
    assert text.startswith("정말") and "109" in text and not text.startswith('"')


def test_small_company_names_are_caught_without_ai_but_common_words_pass():
    for text in ["한빛테크에서 일해요", "미래랩스 팀장이 무서워요", "대한물산 다녀요"]:
        r = check_text(text, kind="post")
        assert not r.ok and r.personal_info, text
    for text in ["신용카드 값이 밀렸어요", "핀테크 회사에 다녀요", "소프트웨어 개발자예요",
                 "전자결재 올렸는데 반려됐어요", "그룹장님이 무서워요", "스터디그룹 사람들이 좋아요"]:
        assert check_text(text, kind="post").ok, text


def test_workplace_words_are_sent_to_ai_as_a_hint(llm):
    seen = {}

    def fake_chat(system, user, **k):
        seen["user"] = user
        return ('{"personal_info": {"detected": true, "spans": ["오렌지마켓"], "suggestion": ""},'
                ' "offensive": {"detected": false}, "crisis": {"detected": false}}')

    llm.setattr(ai_client, "chat", fake_chat)
    r = check_text("작년에 오렌지마켓 입사했는데 너무 힘들어요", kind="post")
    assert "<workplace_hint>오렌지마켓</workplace_hint>" in seen["user"]
    assert not r.ok and r.issues[0].text == "오렌지마켓"
    # 일반 명칭은 후보로 보내지 않는다
    check_text("지금 회사에 다닌 지 3년인데 지쳐요", kind="post")
    assert "workplace_hint" not in seen["user"]


def test_ai_that_points_nowhere_on_a_masked_post_is_asked_again(llm):
    calls = []

    def answer(detected):
        return ('{"personal_info": {"detected": %s, "spans": [], "suggestion": ""},'
                ' "offensive": {"detected": false}, "crisis": {"detected": false}}' % detected)

    def still_found(system, user, **k):
        calls.append(user)
        return answer("true")

    llm.setattr(ai_client, "chat", still_found)
    r = check_text("제 번호 [전화번호]로 옆 가게 사장님이 연락해요", kind="post")
    assert len(calls) == 2 and "[전화번호]" not in calls[1]  # 가림 표시를 지우고 다시 물음
    assert not r.ok and r.suggestion == GUIDE["check"]

    calls.clear()
    replies = iter([answer("true"), answer("false")])
    llm.setattr(ai_client, "chat", lambda *a, **k: (calls.append(1), next(replies))[1])
    assert check_text("제 번호 [전화번호]로 연락이 와요", kind="post").ok  # 가림 표시만 본 거였으면 통과
    assert len(calls) == 2
