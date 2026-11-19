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


def test_character_color_is_saved_and_shown_to_neighbors():
    headers, _ = signup()
    me = http.get("/auth/me", headers=headers).json()
    assert me["color"] == "original"

    nickname = me["nickname"]
    r = http.patch("/users/me", json={"color": "ocean"}, headers=headers)
    assert r.status_code == 200 and r.json()["color"] == "ocean"
    assert r.json()["nickname"] == nickname  # 색만 바꾸면 닉네임은 그대로

    assert http.patch("/users/me", json={"color": "#ff0000"}, headers=headers).status_code == 422

    post_id = write_post(headers)
    viewer, _ = signup()
    assert http.get(f"/posts/{post_id}", headers=viewer).json()["author"]["color"] == "ocean"


def test_post_keeps_the_map_spot_where_it_was_written():
    headers, me_id = signup(job="디자인")
    design = island_id("디자인")
    write_post(headers, island_id=design, map_x=42.5, map_y=61)
    mine = next(n for n in http.get(f"/islands/{design}/neighbors", headers=headers).json() if n["is_me"])
    assert (mine["latest_post"]["map_x"], mine["latest_post"]["map_y"]) == (42.5, 61)

    r = http.post("/posts", headers=headers, json={
        "island_id": design, "topic": "업무량·스트레스", "title": "제목", "content": "내용",
        "comfort_type": "empathy", "map_x": 120,
    })
    assert r.status_code == 422


def test_neighbors_walking_on_the_same_island_see_each_other():
    marketing = island_id("영업")
    a, a_id = signup(job="영업")
    b, b_id = signup(job="영업")
    outsider, _ = signup(job="개발")

    assert http.post(f"/islands/{marketing}/presence", json={"x": 10, "y": 20}, headers=a).json() == []
    seen = http.post(f"/islands/{marketing}/presence", json={"x": 50, "y": 50}, headers=b).json()
    assert [(p["author"]["user_id"], p["x"], p["y"]) for p in seen] == [(a_id, 10, 20)]
    assert "email" not in str(seen)

    # 다른 직무섬에는 들어갈 수 없다
    assert http.post(f"/islands/{marketing}/presence", json={"x": 1, "y": 1}, headers=outsider).status_code == 403

    # 차단하면 서로 안 보인다
    assert http.post("/blocks", json={"user_id": b_id}, headers=a).status_code == 204
    assert http.post(f"/islands/{marketing}/presence", json={"x": 10, "y": 20}, headers=a).json() == []


def test_island_temperature_rises_with_posts_and_comments():
    headers, _ = signup(job="영업")
    sales = island_id("영업")
    before = http.get(f"/islands/{sales}/temperature", headers=headers).json()
    post_id = write_post(headers, island_id=sales, title="실적 압박", content=_unique_text())
    neighbor, _ = signup(job="영업")
    http.post(f"/posts/{post_id}/comments", json={"content": "저도 그랬어요. 힘내요"}, headers=neighbor)
    after = http.get(f"/islands/{sales}/temperature", headers=headers).json()

    assert after["posts"] == before["posts"] + 1
    assert after["comments"] > before["comments"]
    assert after["temperature"] > before["temperature"]
    assert after["level"] in {"cold", "mild", "warm", "hot"}

    http.post(f"/islands/{sales}/presence", json={"x": 50, "y": 50}, headers=neighbor)
    assert http.get(f"/islands/{sales}/temperature", headers=headers).json()["online"] >= 1


def test_already_masked_tokens_do_not_block_the_post():
    from app.ai.check import _llm_issues

    masked = "제 번호 [전화번호]로 연락이 와요"
    assert _llm_issues({"spans": ["[전화번호]"]}, "PERSONAL_INFO", masked, "guide") == []
    assert _llm_issues({"spans": []}, "PERSONAL_INFO", masked, "guide") == []
    # 가린 표현이 없는데 AI가 위치 없이 짚으면 여전히 막는다
    assert len(_llm_issues({"spans": []}, "PERSONAL_INFO", "회사 얘기", "guide")) == 1
    found = _llm_issues({"spans": ["김철수"]}, "PERSONAL_INFO", "김철수 팀장이", "guide")
    assert (found[0].text, found[0].start, found[0].end) == ("김철수", 0, 3)


def test_footprints_show_neighbors_who_visited_today():
    design = island_id("디자인")
    me, _ = signup(job="디자인")
    walker, walker_id = signup(job="디자인")
    writer, writer_id = signup(job="디자인")

    http.post(f"/islands/{design}/presence", json={"x": 30, "y": 40}, headers=walker)
    write_post(writer, island_id=design, title="시안이 계속 반려돼요", content=_unique_text())

    seen = http.get(f"/islands/{design}/footprints", headers=me).json()
    marks = {f["user_id"]: f for f in seen["footprints"]}
    assert walker_id in marks and (marks[walker_id]["x"], marks[walker_id]["y"]) == (30, 40)
    assert writer_id in marks and marks[writer_id]["x"] is None  # 글만 쓴 이웃은 FE가 그 자리에 찍음
    assert seen["visitors"] >= 2 and "email" not in str(seen)

    # 차단한 이웃의 발자국은 안 보인다
    assert http.post("/blocks", json={"user_id": walker_id}, headers=me).status_code == 204
    assert walker_id not in {f["user_id"] for f in http.get(f"/islands/{design}/footprints", headers=me).json()["footprints"]}


def test_bottle_brings_a_worry_from_the_other_island_with_its_story():
    design = island_id("디자인")
    common = island_id(None)
    me, _ = signup(job="디자인")
    writer, _ = signup(job="영업")
    post_id = write_post(writer, island_id=common, title="이직 고민이 길어져요", content=_unique_text())
    root = first_ai_comment(writer, post_id)
    _reply(writer, post_id, root["id"], "한 달 지나서 결국 남기로 했어요. 마음이 편해졌어요")

    # 하루 한 통: 새로고침해도 같은 편지, 직무섬에선 통합섬 고민이 떠내려온다
    bottles = [http.get(f"/islands/{design}/bottle", headers=me).json() for _ in range(3)]
    assert len({b["post_id"] for b in bottles}) == 1 and bottles[0]["island_id"] == common
    assert bottles[0]["next_at"].startswith(bottles[0]["next_at"][:10]) and "T08:00:00" in bottles[0]["next_at"]
    if bottles[0]["post_id"] == post_id:
        assert bottles[0]["follow_up"] == "한 달 지나서 결국 남기로 했어요. 마음이 편해졌어요"

    # 읽으면 사라지고, 다음 날 아침 8시까지 새 편지가 없다
    assert http.post(f"/islands/{design}/bottle/open", headers=me).status_code == 204
    gone = http.get(f"/islands/{design}/bottle", headers=me)
    assert gone.status_code == 404 and "아침 8시" in gone.json()["detail"]

    # 내 글은 유리병으로 오지 않는다
    own = http.get(f"/islands/{common}/bottle", headers=writer)
    assert own.status_code == 404 or own.json()["post_id"] != post_id


def test_private_worry_can_talk_with_ai_only_for_the_author(monkeypatch):
    monkeypatch.setattr(config, "PRIVATE_CHAT_MAX", 2)
    from app.routers import posts as posts_router
    monkeypatch.setattr(posts_router, "PRIVATE_CHAT_MAX", 2)

    me, _ = signup()
    other, _ = signup()
    post_id = write_post(me, visibility="private", title="아무한테도 못 한 이야기", content=_unique_text())

    opening = http.post(f"/posts/{post_id}/ai-chat", json={}, headers=me)
    assert opening.status_code == 200, opening.text
    assert [m["is_ai"] for m in opening.json()["messages"]] == [True]

    talk = http.post(f"/posts/{post_id}/ai-chat", json={"content": "사실 요즘 잠도 잘 못 자요"}, headers=me).json()
    assert [m["is_ai"] for m in talk["messages"]] == [True, False, True]
    assert talk["remaining"] == 1

    # 다른 사람은 대화를 볼 수도, 말을 걸 수도 없다
    assert http.get(f"/posts/{post_id}/ai-chat", headers=other).status_code == 404
    assert http.post(f"/posts/{post_id}/ai-chat", json={"content": "안녕"}, headers=other).status_code == 404

    # 위기 신호가 있으면 상담 안내가 같이 온다
    crisis = http.post(f"/posts/{post_id}/ai-chat", json={"content": "그냥 죽고 싶어요"}, headers=me).json()
    assert crisis["crisis_support"] is not None and crisis["remaining"] == 0
    assert http.post(f"/posts/{post_id}/ai-chat", json={"content": "한 번 더"}, headers=me).status_code == 400

    # 공개 글에서는 쓸 수 없고, 공개로 바꿔도 대화는 댓글로 새지 않는다
    assert http.patch(f"/posts/{post_id}", json={"visibility": "public"}, headers=me).status_code == 200
    assert http.get(f"/posts/{post_id}/ai-chat", headers=me).status_code == 400
    assert "잠도 잘 못 자요" not in str(post_detail(other, post_id))


def test_one_email_start_decides_signup_or_login_and_remember_keeps_longer():
    import jwt
    from app.config import JWT_ALGORITHM, SECRET_KEY

    def days_left(token: str) -> float:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return (payload["exp"] - payload["iat"]) / 86400

    import uuid
    email = f"starter{uuid.uuid4().hex[:8]}@ondo-test.com"

    # 처음 온 이메일 → 가입 코드, 직무·캐릭터를 고른 뒤 가입
    first_r = http.post("/auth/start", json={"email": email})
    assert first_r.status_code == 200, first_r.text
    first = first_r.json()
    assert first["is_new"] is True and first["demo_code"]
    signed = http.post("/auth/signup", json={
        "email": email, "code": first["demo_code"], "job": "개발", "character": "rabbit",
        "agree_privacy": True, "remember": True,
    })
    assert signed.status_code == 201, signed.text
    assert days_left(signed.json()["access_token"]) == pytest.approx(30, abs=0.01)  # 로그인 유지

    # 같은 이메일로 다시 → 로그인 코드, 바로 로그인 (유지 안 하면 1일)
    again = http.post("/auth/start", json={"email": email.upper()}).json()
    assert again["is_new"] is False
    login = http.post("/auth/login", json={"email": email, "code": again["demo_code"]})
    assert login.status_code == 200, login.text
    assert days_left(login.json()["access_token"]) == pytest.approx(1, abs=0.01)

    # 로그인 코드로는 가입할 수 없다 (코드 용도가 섞이지 않음)
    third = http.post("/auth/start", json={"email": email}).json()
    assert http.post("/auth/email-code/verify",
                     json={"email": email, "purpose": "signup", "code": third["demo_code"]}).status_code != 204


def test_activity_titles_grow_and_can_be_chosen():
    author, _ = signup()
    helper, helper_id = signup()
    assert http.get("/users/me/titles", headers=helper).json()["current"] is None

    post_id = write_post(author)
    comment = http.post(f"/posts/{post_id}/comments", json={"content": "저도 그랬어요. 천천히 해 봐요"}, headers=helper).json()
    titles = http.get("/users/me/titles", headers=helper).json()
    assert titles["current"]["key"] == "sprout" and titles["earned_count"] == 1

    # 글쓴이가 고마워요를 누르면 더 높은 칭호가 대표로
    http.post(f"/posts/{post_id}/comments/{comment['id']}/thanks", headers=author)
    detail = http.get(f"/posts/{post_id}", headers=author).json()
    mine = next(c for c in detail["comments"] if c["id"] == comment["id"])
    assert mine["author"]["title"]["key"] == "thanked" and mine["author"]["title"]["tier"] == 2
    assert detail["author"]["title"]["key"] == "first_post"  # 글쓴이는 첫 고민 칭호

    # 얻은 칭호만 대표로 고를 수 있고, 비우면 다시 자동
    assert http.patch("/users/me/title", json={"key": "lighthouse"}, headers=helper).status_code == 400
    chosen = http.patch("/users/me/title", json={"key": "sprout"}, headers=helper).json()
    assert chosen["current"]["key"] == "sprout" and chosen["chosen_key"] == "sprout"
    profile = http.get(f"/users/{helper_id}/profile", params={"island_id": detail["island_id"]}, headers=author).json()
    assert profile["title"]["key"] == "sprout"
    assert http.patch("/users/me/title", json={"key": None}, headers=helper).json()["current"]["key"] == "thanked"


def test_island_keeper_shares_weekly_question_news_and_rules():
    from app.config import TOPICS

    design = island_id("디자인")
    me, _ = signup(job="디자인")
    neighbor, _ = signup(job="디자인")
    before = http.get(f"/islands/{design}/keeper", headers=me).json()["week"]

    post_id = write_post(me, island_id=design, title="시안 피드백이 무서워요", content=_unique_text())
    http.post(f"/posts/{post_id}/comments", json={"content": "저도 그랬어요. 천천히 해요"}, headers=neighbor)
    keeper = http.get(f"/islands/{design}/keeper", headers=me).json()

    assert keeper["name"] == "섬지기" and keeper["greeting"] and keeper["moment"].split()[0].endswith("요일")
    assert keeper["question"]["text"] and keeper["question"]["topic"] in TOPICS
    assert keeper["week"]["posts"] == before["posts"] + 1
    assert keeper["week"]["comforts"] == before["comforts"] + 1
    assert any(str(keeper["report_hide_threshold"]) in rule for rule in keeper["rules"])
    assert {"109", "1577-0199"} <= {r["phone"] for r in keeper["crisis_support"]["resources"]}
    # 다른 직무섬의 섬지기는 볼 수 없다
    assert http.get(f"/islands/{island_id('영업')}/keeper", headers=me).status_code in (403, 404)


def test_keeper_line_follows_weekday_and_time():
    from datetime import datetime

    from app.keeper_lines import LINES, keeper_line

    # 모든 요일 × 시간대 칸에 문구가 3개 이상 있다
    assert len(LINES) == 28 and min(len(v) for v in LINES.values()) >= 3
    assert keeper_line(datetime(2026, 11, 16, 8))[0] == "월요일 아침"  # 2026-11-16은 월요일
    assert keeper_line(datetime(2026, 11, 20, 19))[0] == "금요일 저녁"
    # 월요일 새벽 1시는 아직 '일요일 밤' (출근 걱정에 뒤척이는 시간)
    moment, line = keeper_line(datetime(2026, 11, 23, 1))
    assert moment == "일요일 밤" and line in LINES[(6, "night")]
    # 같은 시각엔 같은 문구, 시간이 바뀌면 같은 칸 안에서 다른 문구로 돈다
    assert keeper_line(datetime(2026, 11, 17, 8, 5)) == keeper_line(datetime(2026, 11, 17, 8, 50))
    assert keeper_line(datetime(2026, 11, 17, 8))[1] != keeper_line(datetime(2026, 11, 17, 9))[1]


def test_post_check_suggests_more_detail_for_thin_posts():
    from app.draft_hint import draft_hint

    assert draft_hint("팀장님이랑 안 맞아요", "팀장님이랑 안 맞아요").reason == "same_as_title"
    assert draft_hint("힘들어요", "ㅠㅠㅠㅠㅠㅠ").reason == "noise"
    assert draft_hint("힘들어요", "아아아아아아아아 진짜").reason == "noise"
    assert draft_hint("퇴사하고 싶어요", "너무 힘들어요").reason == "short"
    # 상황이 담긴 글, 끝에 ㅠㅠ가 조금 붙은 글은 권하지 않는다
    assert draft_hint("팀장님과 자꾸 부딪혀요", "회의 때마다 제 의견을 끝까지 안 듣고 말을 끊으세요.") is None
    assert draft_hint("번아웃", "요즘 아무것도 하기 싫고 주말에도 누워만 있어요ㅠㅠ") is None

    me, _ = signup()
    thin = http.post("/posts/check", json={"title": "퇴사하고 싶어요", "content": "너무 힘들어요"}, headers=me).json()
    assert thin["hint"]["reason"] == "short" and thin["hint"]["tips"] and thin["hint"]["min_length"] == 20
    full = http.post("/posts/check", json={"title": "팀장님과 자꾸 부딪혀요",
                                           "content": "회의 때마다 제 의견을 끝까지 안 듣고 말을 끊으세요."}, headers=me).json()
    assert full["hint"] is None


def test_island_insights_report():
    """섬 고민 리포트: 다른 테스트 글과 섞이지 않게 새 섬을 따로 만들어 계산한다."""
    from datetime import datetime, timedelta, timezone

    import numpy as np

    from app.ai.embedding import upsert_post_embedding
    from app.database import SessionLocal
    from app.insights import MIN_POSTS, copula, daily_window, island_insights, similar_groups, with_and
    from app.models import Comment, Island, Post, Reaction, User

    assert copula("번아웃·무기력") == "이에요" and copula("들어주세요") == "예요"
    assert with_and("야근") == "과" and with_and("회의") == "와"

    # 닮은 글 묶기: 0·1·2가 서로 닮고 3은 동떨어짐 → 3개짜리 묶음 하나
    v = np.array([[1, 0], [0.98, 0.2], [0.97, 0.24], [0, 1]], dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    posts = {i: Post(id=i, title=f"글{i}", topic="워라밸") for i in range(4)}
    groups = similar_groups([0, 1, 2, 3], v @ v.T, 0.9, posts)
    assert len(groups) == 1 and groups[0].size == 3

    users = [signup()[1] for _ in range(4)]
    # 리포트는 오늘 아침 8시까지 쌓인 글만 센다 → 글·공감 시각을 그 전으로 둔다
    now, _ = daily_window(datetime.now(timezone.utc))
    now -= timedelta(minutes=30)
    with SessionLocal() as db:
        island = Island(type="job", job="리포트테스트", name="리포트섬")  # 테스트마다 새 DB라 한 번만 만들어짐
        db.add(island)
        db.commit()
        overtime = "야근이 너무 많아서 퇴근하고 나면 아무것도 못 하고 잠만 자요"
        rows = [
            (users[0], "업무량·스트레스", "야근이 너무 많아요", overtime, 0),
            (users[1], "업무량·스트레스", "야근 때문에 지쳐요", overtime + " 매일", 1),
            (users[2], "업무량·스트레스", "야근이 계속돼요", overtime + " 주말에도", 2),
            (users[3], "연애·이별", "헤어지고 일이 손에 안 잡혀요", "이별 뒤로 회의 때도 멍하게 있어요", 3),
            (users[3], "경제·금전", "월급이 그대로예요", "물가는 오르는데 연봉은 몇 년째 같아요", 30),
        ]
        made = []
        for uid, topic, title, content, hours_ago in rows:
            p = Post(user_id=uid, island_id=island.id, topic=topic, title=title, content=content,
                     comfort_type="empathy", visibility="public", status="published",
                     created_at=now - timedelta(hours=hours_ago))
            db.add(p)
            db.commit()
            upsert_post_embedding(db, p)
            made.append(p)
        # 오늘 공감 2개가 모인 글, 이웃 댓글이 달린 글
        db.add_all([Reaction(post_id=made[1].id, user_id=users[2], created_at=now),
                    Reaction(post_id=made[1].id, user_id=users[3], created_at=now)])
        db.add(Comment(post_id=made[3].id, user_id=users[0], content="저도 그랬어요"))
        db.commit()

        me = db.get(User, users[0])
        out = island_insights(db, island, me, set())
        assert out.enough and out.total_posts == MIN_POSTS
        assert out.topics[0].key == "업무량·스트레스" and out.topics[0].count == 3
        assert out.categories[0].label == "업무·직장생활"
        assert out.rising.topic == "업무량·스트레스" and out.rising.last_week == 0
        assert sum(out.time.days) == 5 and out.comfort[0].label == "들어주세요"
        assert out.groups and out.groups[0].size >= 3  # 야근 글 셋이 한 묶음
        assert out.me.post_id == made[0].id and out.me.neighbors == 2 and out.me.topic_rank == 1
        assert out.warmest.post_id == made[1].id and out.warmest.count == 2
        assert out.waiting is not None and out.waiting.post_id not in (made[0].id, made[3].id)  # 내 글·답 달린 글 제외
        assert any("업무량·스트레스" in line for line in out.headlines)
        assert out.as_of.hour == 8 and out.next_at - out.as_of == timedelta(days=1)

        # 아침 8시 뒤에 올라온 글은 내일 리포트에 들어간다 (오늘 리포트는 그대로)
        late = Post(user_id=users[2], island_id=island.id, topic="워라밸", title="늦게 쓴 글", content="오늘 아침에 썼어요",
                    comfort_type="empathy", visibility="public", status="published",
                    created_at=out.as_of + timedelta(minutes=5))
        db.add(late)
        db.commit()
        same = island_insights(db, island, me, set())
        assert same.total_posts == MIN_POSTS
        tomorrow = island_insights(db, island, me, set(), now=out.next_at + timedelta(minutes=1))
        assert tomorrow.total_posts == MIN_POSTS + 1 and tomorrow.as_of == out.next_at

        # 차단한 사람의 글은 통째로 빠진다 → 4개라 리포트를 보여 주지 않음
        hidden = island_insights(db, island, me, {users[3]})
        assert hidden.total_posts == 3 and not hidden.enough and hidden.headlines == []


def test_island_insights_api_respects_island_access():
    me, _ = signup(job="영업")
    r = http.get(f"/islands/{island_id(None)}/insights", headers=me)
    assert r.status_code == 200, r.text
    assert {"enough", "headlines", "topics", "groups", "me", "warmest", "waiting"} <= set(r.json())
    assert http.get(f"/islands/{island_id('개발')}/insights", headers=me).status_code == 403


def test_bottle_day_turns_at_8am_kst():
    from datetime import datetime, timedelta, timezone

    from app.routers.islands import bottle_day

    kst = timezone(timedelta(hours=9))
    # 아침 7시 59분은 아직 어제 편지, 8시부터 오늘 편지
    assert bottle_day(datetime(2026, 11, 20, 7, 59, tzinfo=kst))[0] == "2026-11-19"
    day, next_at = bottle_day(datetime(2026, 11, 20, 8, 0, tzinfo=kst))
    assert day == "2026-11-20" and next_at == datetime(2026, 11, 21, 8, 0, tzinfo=kst)


def test_similar_worries_share_one_map_bubble():
    """내용이 닮은 이웃 고민은 지도에서 말풍선 하나로 합쳐진다. 내 글은 따로 보인다."""
    from app.database import SessionLocal
    from app.insights import _vector_cache

    me, my_id = signup(job="영업")
    sales = island_id("영업")
    overtime = "야근이 너무 많아서 퇴근하고 나면 아무것도 못 하고 잠만 자요 매일 반복돼요"
    writers = [signup(job="영업") for _ in range(3)]
    ids = [write_post(h, island_id=sales, title=f"야근 고민 {i}", content=overtime) for i, (h, _) in enumerate(writers)]
    write_post(me, island_id=sales, title="야근 고민 나도", content=overtime)
    _vector_cache.clear()

    neighbors = http.get(f"/islands/{sales}/neighbors", headers=me).json()
    posts = {n["latest_post"]["id"]: (n["latest_post"], n["is_me"]) for n in neighbors if n["latest_post"]}
    leads = {posts[pid][0]["bubble"] for pid in ids}
    assert len(leads) == 1 and None not in leads  # 닮은 세 글이 한 말풍선으로
    lead = leads.pop()
    assert posts[lead][0]["bubble_size"] >= 3
    mine = next(p for p, is_me in posts.values() if is_me)
    assert mine["bubble"] is None  # 내 글은 합치지 않는다


def test_signup_can_pick_character_color():
    """가입 화면 팔레트: 가입할 때 고른 색감이 그대로 저장된다. 없는 색감은 422."""
    from support import email_code

    email = "palette-signup@ondo-test.com"
    body = {"email": email, "job": "개발", "years": None, "character": "rabbit",
            "agree_privacy": True, "color": "ocean"}
    code = email_code(email, "signup")
    bad = http.post("/auth/signup", json={**body, "code": code, "color": "neon"})
    assert bad.status_code == 422  # 형식 검사에서 막혀 코드는 그대로 남는다

    r = http.post("/auth/signup", json={**body, "code": code})
    assert r.status_code == 201, r.text
    me = http.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["color"] == "ocean"
