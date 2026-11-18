import itertools

import pytest

from app import config, moderation
from app.ai import prompts
from app.ai.check import CheckResult
from support import first_ai_comment, http, island_id, post_detail, signup, write_post

_topic = itertools.count(1)


@pytest.fixture
def trusted(monkeypatch):
    monkeypatch.setattr(config, "REPORT_TRUSTED_ACCOUNT_HOURS", 0)


@pytest.fixture
def admin(monkeypatch):
    headers, _ = signup()
    email = http.get("/auth/me", headers=headers).json()["email"]
    monkeypatch.setattr(config, "ADMIN_EMAILS", {email.lower()})
    return headers


def _report(target_type: str, target_id: int, count: int) -> list[dict]:
    reporters = [signup()[0] for _ in range(count)]
    for headers in reporters:
        r = http.post("/reports", json={"target_type": target_type, "target_id": target_id, "reason": "불편해요"},
                      headers=headers)
        assert r.status_code == 204, r.text
    return reporters


def _cases(admin_headers: dict, state: str = "open") -> list[dict]:
    r = http.get(f"/admin/moderation?state={state}", headers=admin_headers)
    assert r.status_code == 200, r.text
    return r.json()


def _case_for(admin_headers: dict, target_type: str, target_id: int, state: str = "open") -> dict | None:
    return next((c for c in _cases(admin_headers, state)
                 if c["target_type"] == target_type and c["target_id"] == target_id), None)


def _notification_types(headers: dict, post_id: int) -> list[str]:
    return [n["type"] for n in http.get("/notifications?limit=50", headers=headers).json()["notifications"]
            if n["post_id"] == post_id]


def _reply(headers: dict, post_id: int, parent_id: int, content: str = "조금 더 이야기해 볼게요") -> dict:
    r = http.post(f"/posts/{post_id}/comments", json={"content": content, "parent_id": parent_id}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _ai_thread(headers: dict, post_id: int, root_id: int) -> list[dict]:
    return [c for c in post_detail(headers, post_id)["comments"] if c["parent_id"] == root_id and c["is_ai"]]


def _unique_text() -> str:
    n = next(_topic)
    return f"분기 실적 압박 {n}호 거래처 미팅 {n}번 연속 취소 영업 목표 {n * 7}건 미달"


def test_reports_below_force_threshold_wait_for_review_instead_of_hiding(trusted, admin):
    author, _ = signup()
    post_id = write_post(author)
    reporters = _report("post", post_id, int(config.REPORT_HIDE_THRESHOLD))

    assert http.get(f"/posts/{post_id}", headers=reporters[0]).status_code == 200
    case = _case_for(admin, "post", post_id)
    assert case["state"] == "review"
    assert case["report_score"] == config.REPORT_HIDE_THRESHOLD
    assert case["reasons"] and case["preview"]


def test_ai_flag_hides_at_first_threshold(trusted, admin, monkeypatch):
    monkeypatch.setattr(moderation, "check_text", lambda text, kind="comment": CheckResult(ok=False, reason="공격적"))
    author, _ = signup()
    post_id = write_post(author)
    reporters = _report("post", post_id, int(config.REPORT_HIDE_THRESHOLD))

    assert http.get(f"/posts/{post_id}", headers=reporters[0]).status_code == 404
    assert post_detail(author, post_id)["status"] == "hidden"
    assert "hidden" in _notification_types(author, post_id)
    assert _case_for(admin, "post", post_id)["ai_flagged"] is True


def test_force_threshold_hides_post_and_edit_keeps_it_hidden(trusted):
    author, _ = signup()
    post_id = write_post(author)
    reporters = _report("post", post_id, int(config.REPORT_FORCE_HIDE_THRESHOLD))

    assert http.get(f"/posts/{post_id}", headers=reporters[0]).status_code == 404
    http.patch(f"/posts/{post_id}", json={"title": "고쳐서 다시 올려요"}, headers=author)
    assert post_detail(author, post_id)["status"] == "hidden"
    listed = http.get(f"/islands/{island_id()}/posts?limit=50", headers=author).json()["posts"]
    assert post_id not in [p["id"] for p in listed]


def test_new_accounts_count_half_so_sock_puppets_cannot_hide(admin):
    author, _ = signup()
    post_id = write_post(author)
    reporters = _report("post", post_id, int(config.REPORT_FORCE_HIDE_THRESHOLD))

    assert http.get(f"/posts/{post_id}", headers=reporters[0]).status_code == 200
    case = _case_for(admin, "post", post_id)
    assert case["state"] == "review"
    assert case["report_score"] == config.REPORT_FORCE_HIDE_THRESHOLD / 2


def test_force_threshold_hides_comment_and_excludes_it_from_counts(trusted):
    author, _ = signup()
    commenter, _ = signup()
    post_id = write_post(author)
    comment = http.post(f"/posts/{post_id}/comments", json={"content": "그냥 참으세요"}, headers=commenter).json()
    _report("comment", comment["id"], int(config.REPORT_FORCE_HIDE_THRESHOLD))

    hidden = next(c for c in post_detail(author, post_id)["comments"] if c["id"] == comment["id"])
    assert hidden["is_hidden"] is True
    assert hidden["content"] == config.HIDDEN_COMMENT
    assert hidden["author"] is None
    listed = http.get(f"/islands/{island_id()}/posts?limit=50", headers=author).json()["posts"]
    assert next(p for p in listed if p["id"] == post_id)["comment_count"] == 1


def test_owner_appeals_and_admin_restores(trusted, admin):
    author, _ = signup()
    stranger, _ = signup()
    post_id = write_post(author)
    reporters = _report("post", post_id, int(config.REPORT_FORCE_HIDE_THRESHOLD))
    appeal = {"target_type": "post", "target_id": post_id, "reason": "고민을 나눈 글이에요"}

    assert http.post("/reports/appeal", json=appeal, headers=stranger).status_code == 404
    assert http.post("/reports/appeal", json=appeal, headers=author).status_code == 204
    assert http.post("/reports/appeal", json=appeal, headers=author).status_code == 409

    case = _cases(admin)[0]
    assert case["target_id"] == post_id and case["appealed"] is True
    assert http.post(f"/admin/moderation/{case['id']}", json={"action": "restore"}, headers=admin).status_code == 204

    assert http.get(f"/posts/{post_id}", headers=reporters[0]).status_code == 200
    assert "restored" in _notification_types(author, post_id)
    assert _case_for(admin, "post", post_id, "restored") is not None


def test_restored_post_stays_visible_while_unchanged(trusted, admin):
    author, _ = signup()
    post_id = write_post(author)
    _report("post", post_id, int(config.REPORT_HIDE_THRESHOLD))
    case = _case_for(admin, "post", post_id)
    http.post(f"/admin/moderation/{case['id']}", json={"action": "restore"}, headers=admin)

    reporters = _report("post", post_id, int(config.REPORT_FORCE_HIDE_THRESHOLD) * 2)
    assert http.get(f"/posts/{post_id}", headers=reporters[0]).status_code == 200
    case = _case_for(admin, "post", post_id)
    assert case["state"] == "review" and case["protected"] is True
    assert "hidden" not in _notification_types(author, post_id)


def test_restored_post_loses_protection_after_edit(trusted, admin):
    author, _ = signup()
    post_id = write_post(author)
    _report("post", post_id, int(config.REPORT_HIDE_THRESHOLD))
    case = _case_for(admin, "post", post_id)
    http.post(f"/admin/moderation/{case['id']}", json={"action": "restore"}, headers=admin)

    r = http.patch(f"/posts/{post_id}", json={"content": "복구된 뒤에 내용을 바꿔 다시 올렸어요."}, headers=author)
    assert r.status_code == 200, r.text
    reporters = _report("post", post_id, int(config.REPORT_FORCE_HIDE_THRESHOLD))
    assert http.get(f"/posts/{post_id}", headers=reporters[0]).status_code == 404
    assert post_detail(author, post_id)["status"] == "hidden"


def test_visibility_change_keeps_restored_protection(trusted, admin):
    author, _ = signup()
    post_id = write_post(author)
    _report("post", post_id, int(config.REPORT_HIDE_THRESHOLD))
    case = _case_for(admin, "post", post_id)
    http.post(f"/admin/moderation/{case['id']}", json={"action": "restore"}, headers=admin)

    http.patch(f"/posts/{post_id}", json={"visibility": "private"}, headers=author)
    http.patch(f"/posts/{post_id}", json={"visibility": "public"}, headers=author)
    reporters = _report("post", post_id, int(config.REPORT_FORCE_HIDE_THRESHOLD))
    assert http.get(f"/posts/{post_id}", headers=reporters[0]).status_code == 200


def test_admin_hides_reviewed_comment(trusted, admin):
    author, _ = signup()
    commenter, _ = signup()
    post_id = write_post(author)
    comment = http.post(f"/posts/{post_id}/comments", json={"content": "별일 아니에요"}, headers=commenter).json()
    _report("comment", comment["id"], int(config.REPORT_HIDE_THRESHOLD))
    case = _case_for(admin, "comment", comment["id"])

    assert http.post(f"/admin/moderation/{case['id']}", json={"action": "hide"}, headers=admin).status_code == 204
    hidden = next(c for c in post_detail(author, post_id)["comments"] if c["id"] == comment["id"])
    assert hidden["is_hidden"] is True
    assert "hidden" in _notification_types(commenter, post_id)


def test_admin_api_is_forbidden_for_members():
    member, _ = signup()
    assert http.get("/admin/moderation", headers=member).status_code == 403
    assert http.post("/admin/moderation/1", json={"action": "restore"}, headers=member).status_code == 403


def test_ai_keeps_company_until_limit(monkeypatch):
    monkeypatch.setattr(config, "AI_FOLLOWUP_MAX", 5)
    author, _ = signup()
    post_id = write_post(author)
    root = first_ai_comment(author, post_id)
    pending = [_reply(author, post_id, root["id"], f"{i}번째 이야기")["ai_reply_pending"] for i in range(6)]
    assert pending == [True] * 5 + [False]
    assert len(_ai_thread(author, post_id, root["id"])) == 5


def test_ai_hands_off_once_a_neighbor_arrives():
    author, _ = signup()
    neighbor, _ = signup()
    post_id = write_post(author)
    root = first_ai_comment(author, post_id)
    _reply(author, post_id, root["id"], "첫 번째 이야기")

    http.post(f"/posts/{post_id}/comments", json={"content": "저도 그런 적 있어요"}, headers=neighbor)
    assert _reply(author, post_id, root["id"], "이웃이 와 줬네요")["ai_reply_pending"] is True
    assert _ai_thread(author, post_id, root["id"])[-1]["content"] == prompts.FALLBACK_FOLLOWUP_NEIGHBORS

    assert _reply(author, post_id, root["id"], "고마워요")["ai_reply_pending"] is False
    assert len(_ai_thread(author, post_id, root["id"])) == 2


def test_ai_daily_reply_limit_per_author(monkeypatch):
    monkeypatch.setattr(config, "AI_DAILY_REPLY_LIMIT", 2)
    author, _ = signup()
    post_a = write_post(author)
    post_b = write_post(author)
    root_a = first_ai_comment(author, post_a)
    root_b = first_ai_comment(author, post_b)
    assert _reply(author, post_a, root_a["id"])["ai_reply_pending"] is True
    assert _reply(author, post_a, root_a["id"])["ai_reply_pending"] is True
    assert _reply(author, post_b, root_b["id"])["ai_reply_pending"] is False


def test_similar_neighbors_are_invited_unless_they_opt_out():
    text = _unique_text()
    sales = island_id("영업")
    veteran, _ = signup(job="영업")
    quiet, _ = signup(job="영업")
    newcomer, _ = signup(job="영업")
    assert http.patch("/users/me", json={"accept_invites": False}, headers=quiet).json()["accept_invites"] is False
    write_post(veteran, island_id=sales, title="실적 압박", content=text)
    write_post(quiet, island_id=sales, title="실적 압박", content=text)

    post_id = write_post(newcomer, island_id=sales, title="실적 압박이 심해요", content=text)
    invites = [n for n in http.get("/notifications", headers=veteran).json()["notifications"]
               if n["type"] == "invite" and n["post_id"] == post_id]
    assert len(invites) == 1
    assert invites[0]["is_ai"] is False and invites[0]["actor"] is None
    assert "invite" not in _notification_types(quiet, post_id)
    assert "invite" not in _notification_types(newcomer, post_id)


def test_similar_posts_show_only_answered_experiences():
    text = _unique_text()
    sales = island_id("영업")
    answered_author, _ = signup(job="영업")
    lonely_author, _ = signup(job="영업")
    helper, _ = signup(job="영업")
    reader, _ = signup(job="영업")
    answered = write_post(answered_author, island_id=sales, title="비슷한 고민", content=text)
    lonely = write_post(lonely_author, island_id=sales, title="비슷한 고민", content=text)
    http.post(f"/posts/{answered}/comments", json={"content": "저는 이렇게 버텼어요"}, headers=helper)

    current = write_post(reader, island_id=sales, title="저도 같은 고민", content=text)
    similar = http.get(f"/posts/{current}/similar", headers=reader).json()
    ids = [p["id"] for p in similar]
    assert answered in ids and lonely not in ids and current not in ids
    assert similar[0]["similarity"] > 0


def test_author_thanks_neighbor_and_it_shows_in_summary():
    author, _ = signup()
    neighbor, _ = signup()
    stranger, _ = signup()
    post_id = write_post(author)
    comment = http.post(f"/posts/{post_id}/comments", json={"content": "저도 겪어 봤어요"}, headers=neighbor).json()
    ai = first_ai_comment(author, post_id)
    url = f"/posts/{post_id}/comments/{comment['id']}/thanks"

    assert http.post(url, headers=stranger).status_code == 403
    assert http.post(f"/posts/{post_id}/comments/{ai['id']}/thanks", headers=author).status_code == 404
    assert http.post(url, headers=author).json() == {"thanked": True}
    assert next(c for c in post_detail(neighbor, post_id)["comments"] if c["id"] == comment["id"])["thanked"] is True

    notes = [n for n in http.get("/notifications", headers=neighbor).json()["notifications"] if n["type"] == "thanks"]
    assert notes and notes[0]["actor"] is not None and notes[0]["is_ai"] is False
    summary = http.get("/users/me/summary", headers=neighbor).json()
    assert summary == {"post_count": 0, "comment_count": 1, "thanks_received": 1, "posts_helped": 1}

    assert http.post(url, headers=author).json() == {"thanked": False}
    assert http.get("/users/me/summary", headers=neighbor).json()["thanks_received"] == 0


def test_impact_stats_include_utility_metrics():
    stats = http.get("/stats/impact").json()
    for key in ("thanked_comments", "invites_sent", "invited_posts_answered", "reports_reviewed", "reports_restored"):
        assert key in stats


def test_unread_count_skips_notifications_for_posts_i_can_no_longer_see():
    author, _ = signup()
    neighbor, _ = signup()
    post_id = write_post(author)
    comment = http.post(f"/posts/{post_id}/comments", json={"content": "저도 그랬어요"}, headers=neighbor).json()
    http.post(f"/posts/{post_id}/comments", json={"content": "고마워요", "parent_id": comment["id"]}, headers=author)
    http.post(f"/posts/{post_id}/comments/{comment['id']}/thanks", headers=author)
    before = http.get("/notifications", headers=neighbor).json()
    assert before["unread_count"] >= 1

    http.patch(f"/posts/{post_id}", json={"visibility": "private"}, headers=author)
    after = http.get("/notifications", headers=neighbor).json()
    assert all(n["post_id"] != post_id for n in after["notifications"])
    assert after["unread_count"] == before["unread_count"] - sum(
        1 for n in before["notifications"] if n["post_id"] == post_id and not n["is_read"]
    )
