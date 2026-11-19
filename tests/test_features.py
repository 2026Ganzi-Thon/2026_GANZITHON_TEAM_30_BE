from app import config
from support import first_ai_comment, http, island_id, post_detail, signup, write_post


def _reply(headers: dict, post_id: int, parent_id: int, content: str = "고마워요. 사실 더 힘든 일이 있었어요"):
    r = http.post(f"/posts/{post_id}/comments", json={"content": content, "parent_id": parent_id}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _thread(headers: dict, post_id: int, root_id: int) -> list[dict]:
    return [c for c in post_detail(headers, post_id)["comments"] if c["parent_id"] == root_id]


def test_ai_follows_up_when_author_replies_to_ai_comment():
    author, _ = signup()
    post_id = write_post(author, comfort_type="opinion")
    root = first_ai_comment(author, post_id)

    reply = _reply(author, post_id, root["id"])
    assert reply["parent_id"] == root["id"]
    assert reply["ai_reply_pending"] is True

    thread = _thread(author, post_id, root["id"])
    assert [c["is_ai"] for c in thread] == [False, True]
    assert thread[1]["author"] is None

    notifications = http.get("/notifications", headers=author).json()["notifications"]
    assert any(n["type"] == "reply" and n["is_ai"] and n["post_id"] == post_id for n in notifications)


def test_reply_to_a_reply_joins_the_same_thread():
    author, _ = signup()
    post_id = write_post(author)
    root = first_ai_comment(author, post_id)
    _reply(author, post_id, root["id"])
    ai_follow_up = _thread(author, post_id, root["id"])[-1]

    second = _reply(author, post_id, ai_follow_up["id"], "맞아요. 조금 나아졌어요")
    assert second["parent_id"] == root["id"]
    assert [c["is_ai"] for c in _thread(author, post_id, root["id"])] == [False, True, False, True]


def test_ai_follow_up_stops_after_limit_and_hands_off(monkeypatch):
    monkeypatch.setattr(config, "AI_FOLLOWUP_MAX", 3)
    author, _ = signup()
    post_id = write_post(author)
    root = first_ai_comment(author, post_id)
    pending = [_reply(author, post_id, root["id"], f"{i}번째 답글이에요")["ai_reply_pending"]
               for i in range(config.AI_FOLLOWUP_MAX + 1)]
    assert pending == [True] * config.AI_FOLLOWUP_MAX + [False]

    ai_replies = [c for c in _thread(author, post_id, root["id"]) if c["is_ai"]]
    assert len(ai_replies) == config.AI_FOLLOWUP_MAX
    assert "이웃" in ai_replies[-1]["content"]


def test_only_post_author_gets_ai_follow_up():
    author, _ = signup()
    neighbor, _ = signup()
    post_id = write_post(author)
    root = first_ai_comment(author, post_id)
    reply = _reply(neighbor, post_id, root["id"], "저도 같은 마음이에요")
    assert reply["ai_reply_pending"] is False
    assert [c["is_ai"] for c in _thread(author, post_id, root["id"])] == [False]


def test_crisis_reply_returns_support_and_ai_shares_hotline():
    author, _ = signup()
    post_id = write_post(author)
    root = first_ai_comment(author, post_id)
    reply = _reply(author, post_id, root["id"], "사실 요즘 죽고 싶다는 생각이 들어요")
    assert reply["crisis_support"]["resources"][0]["phone"] == "109"
    ai = _thread(author, post_id, root["id"])[-1]
    assert ai["is_ai"] and "109" in ai["content"]


def test_reply_parent_must_belong_to_same_post():
    author, _ = signup()
    post_a = write_post(author)
    post_b = write_post(author)
    root_b = first_ai_comment(author, post_b)
    r = http.post(f"/posts/{post_a}/comments", json={"content": "엉뚱한 곳", "parent_id": root_b["id"]}, headers=author)
    assert r.status_code == 404
    r = http.post(f"/posts/{post_a}/comments", json={"content": "없는 댓글", "parent_id": 99999999}, headers=author)
    assert r.status_code == 404


def test_neighbor_reply_notifies_comment_author():
    author, _ = signup()
    commenter, _ = signup()
    replier, _ = signup()
    post_id = write_post(author)
    comment = http.post(f"/posts/{post_id}/comments", json={"content": "저도 그랬어요"}, headers=commenter).json()
    _reply(replier, post_id, comment["id"], "두 분 모두 응원해요")
    notifications = http.get("/notifications", headers=commenter).json()["notifications"]
    assert any(n["type"] == "reply" and n["post_id"] == post_id for n in notifications)
    assert http.get("/islands", headers=commenter).json()[0]["has_new_comment"] is True


def test_waiting_filter_shows_posts_without_neighbor_comments():
    author, _ = signup()
    neighbor, _ = signup()
    post_id = write_post(author, title="아직 아무도 답이 없어요")

    waiting = http.get(f"/islands/{island_id()}/posts?waiting=true&limit=50", headers=neighbor).json()["posts"]
    assert post_id in [p["id"] for p in waiting]
    assert next(p for p in waiting if p["id"] == post_id)["waiting"] is True

    http.post(f"/posts/{post_id}/comments", json={"content": "저도 같은 고민이에요"}, headers=neighbor)
    waiting = http.get(f"/islands/{island_id()}/posts?waiting=true&limit=50", headers=neighbor).json()["posts"]
    assert post_id not in [p["id"] for p in waiting]


def test_impact_stats_count_ai_and_neighbor_responses():
    author, _ = signup()
    neighbor, _ = signup()
    post_id = write_post(author)
    root = first_ai_comment(author, post_id)
    _reply(author, post_id, root["id"])
    http.post(f"/posts/{post_id}/comments", json={"content": "응원해요"}, headers=neighbor)

    stats = http.get("/stats/impact").json()
    assert stats["public_posts"] >= 1
    assert stats["posts_with_first_response"] >= 1
    assert stats["median_minutes_to_first_response"] is not None
    assert stats["ai_conversations"] >= 1
    assert stats["ai_follow_up_replies"] >= 1
    assert stats["neighbor_comments"] >= 1


def test_comment_with_bad_words_is_rejected_with_code():
    author, _ = signup()
    post_id = write_post(author)
    r = http.post(f"/posts/{post_id}/comments", json={"content": "시발 그냥 참아"}, headers=author)
    assert r.status_code == 422
    assert r.json()["code"] == "NEED_EDIT"


def test_island_posts_filter_by_topic_category():
    """고민 필터의 '고민 주제'(대분류)로 목록을 거른다: 고른 대분류의 소분류 글만 나온다."""
    author, _ = signup()
    work = write_post(author, topic="업무량·스트레스", title="회의가 너무 많아서 힘들어요",
                      content="하루에 회의가 다섯 개라 정작 일을 못 해서 늘 늦게 퇴근해요.")
    life = write_post(author, topic="건강·생활습관", title="잠들기 전까지 휴대폰을 봐요",
                      content="자기 전에 휴대폰을 오래 봐서 아침마다 너무 피곤하고 지쳐요.")
    url = f"/islands/{island_id()}/posts?limit=50"

    ids = [p["id"] for p in http.get(url + "&category=업무·직장생활", headers=author).json()["posts"]]
    assert work in ids and life not in ids

    ids = [p["id"] for p in http.get(url + "&category=업무·직장생활&category=관계·일상", headers=author).json()["posts"]]
    assert work in ids and life in ids

    assert http.get(url + "&category=없는주제", headers=author).status_code == 422
